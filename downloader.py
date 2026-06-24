from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


ProgressCallback = Callable[[int, int, float], None]
StatusCallback = Callable[[str], None]


class DownloadError(RuntimeError):
    pass


@dataclass
class RemoteFile:
    url: str
    filename: str
    size: int
    accepts_ranges: bool


def _safe_filename(name: str) -> str:
    name = urllib.parse.unquote(name).strip().strip('"')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.rstrip(". ")
    return name or "download.bin"


def _filename_from_url(url: str) -> str:
    path_name = Path(urllib.parse.urlparse(url).path).name
    return _safe_filename(path_name) if path_name else ""


def _has_extension(filename: str) -> bool:
    return bool(Path(filename).suffix)


def _filename_from_headers(headers) -> str:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if match:
        return _safe_filename(match.group(1))

    match = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    if match:
        return _safe_filename(match.group(1))

    return ""


def _best_filename(original_url: str, final_url: str, headers) -> str:
    original_name = _filename_from_url(original_url)
    header_name = _filename_from_headers(headers)
    final_name = _filename_from_url(final_url)

    for name in (original_name, header_name, final_name):
        if name and _has_extension(name):
            return name

    return original_name or header_name or final_name or "download.bin"


def _target_filename(output: Optional[str], inferred: str) -> str:
    inferred = _safe_filename(inferred)
    if not output:
        return inferred

    target = _safe_filename(output)
    inferred_suffix = Path(inferred).suffix
    if inferred_suffix and not Path(target).suffix:
        target += inferred_suffix
    return target


def inspect_remote(url: str, timeout: int = 20) -> RemoteFile:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "MultiThreadDownloader/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            headers = response.headers
            size = int(headers.get("Content-Length") or 0)
            accepts_ranges = headers.get("Accept-Ranges", "").lower() == "bytes"
            filename = _best_filename(url, final_url, headers)
            return RemoteFile(final_url, filename, size, accepts_ranges)
    except urllib.error.HTTPError as exc:
        if exc.code not in {403, 405, 501}:
            raise DownloadError(f"HEAD request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"Cannot connect: {exc.reason}") from exc

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MultiThreadDownloader/1.0", "Range": "bytes=0-0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            headers = response.headers
            content_range = headers.get("Content-Range", "")
            size = 0
            match = re.search(r"/(\d+)$", content_range)
            if match:
                size = int(match.group(1))
            else:
                size = int(headers.get("Content-Length") or 0)
            accepts_ranges = response.status == 206
            filename = _best_filename(url, final_url, headers)
            return RemoteFile(final_url, filename, size, accepts_ranges)
    except urllib.error.URLError as exc:
        raise DownloadError(f"Cannot inspect remote file: {exc}") from exc


class MultiThreadDownloader:
    def __init__(
        self,
        url: str,
        output: Optional[str] = None,
        directory: str = ".",
        threads: int = 8,
        chunk_size: int = 1024 * 256,
        retries: int = 5,
        timeout: int = 30,
        progress_callback: Optional[ProgressCallback] = None,
        status_callback: Optional[StatusCallback] = None,
    ) -> None:
        self.url = url
        self.output = output
        self.directory = Path(directory)
        self.threads = max(1, min(int(threads), 32))
        self.chunk_size = chunk_size
        self.retries = max(1, int(retries))
        self.timeout = timeout
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._downloaded = 0
        self._total = 0
        self._last_state_save = 0.0

    def cancel(self) -> None:
        self.cancel_event.set()

    def download(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        remote = inspect_remote(self.url, timeout=self.timeout)
        target = self.directory / _target_filename(self.output, remote.filename)
        self._status(f"Remote file: {remote.filename}")

        if not remote.size or not remote.accepts_ranges or self.threads == 1:
            return self._download_single(remote.url, target, remote.size)

        return self._download_multi(remote.url, target, remote.size)

    def _download_single(self, url: str, target: Path, size: int) -> Path:
        part_path = target.with_suffix(target.suffix + ".part")
        self._total = size
        self._status("Server does not provide usable range metadata; using single stream.")

        failures = 0
        while not self.cancel_event.is_set():
            existing = part_path.stat().st_size if part_path.exists() else 0
            if size and existing >= size:
                self._downloaded = existing
                break

            headers = {"User-Agent": "MultiThreadDownloader/1.0"}
            mode = "wb"
            if existing and size:
                headers["Range"] = f"bytes={existing}-"
                mode = "ab"
                self._downloaded = existing

            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if existing and response.status != 206:
                        mode = "wb"
                        self._downloaded = 0
                    with open(part_path, mode) as handle:
                        while not self.cancel_event.is_set():
                            data = response.read(self.chunk_size)
                            if not data:
                                break
                            handle.write(data)
                            self._add_progress(len(data))
                if size and part_path.stat().st_size <= existing:
                    raise DownloadError("Connection closed without receiving more data.")
                if not size:
                    break
                failures = 0
            except Exception as exc:
                failures += 1
                if failures >= self.retries:
                    raise DownloadError(f"Download failed after {failures} attempts: {exc}") from exc
                self._status(f"Retrying single stream ({failures}/{self.retries})...")
                time.sleep(min(2 * failures, 10))

        if self.cancel_event.is_set():
            raise DownloadError("Download cancelled.")

        part_path.replace(target)
        self._report_progress()
        self._status("Download complete.")
        return target

    def _download_multi(self, url: str, target: Path, size: int) -> Path:
        part_path = target.with_suffix(target.suffix + ".part")
        state_path = target.with_suffix(target.suffix + ".state.json")
        segments = self._load_or_create_segments(state_path, url, size)
        self._total = size
        self._downloaded = sum(segment["downloaded"] for segment in segments)

        with open(part_path, "ab") as handle:
            handle.truncate(size)

        self._status(f"Downloading with {min(self.threads, len(segments))} threads.")
        errors: list[BaseException] = []
        queue = list(range(len(segments)))
        queue_lock = threading.Lock()

        def next_index() -> Optional[int]:
            with queue_lock:
                return queue.pop(0) if queue else None

        def worker() -> None:
            while not self.cancel_event.is_set():
                index = next_index()
                if index is None:
                    return
                try:
                    self._download_segment(url, part_path, segments, index, state_path)
                except BaseException as exc:
                    with self._lock:
                        errors.append(exc)
                    self.cancel_event.set()
                    return

        workers = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(self.threads, len(segments)))
        ]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join()

        self._save_state(state_path, url, size, segments, force=True)

        if errors:
            raise DownloadError(str(errors[0])) from errors[0]
        if self.cancel_event.is_set():
            raise DownloadError("Download cancelled.")
        if any(segment["downloaded"] < segment["end"] - segment["start"] + 1 for segment in segments):
            raise DownloadError("Download incomplete; run again to resume.")

        state_path.unlink(missing_ok=True)
        part_path.replace(target)
        self._report_progress()
        self._status("Download complete.")
        return target

    def _load_or_create_segments(self, state_path: Path, url: str, size: int) -> list[dict]:
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("url") == url and state.get("size") == size:
                    return state["segments"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                pass

        segment_count = min(self.threads, size) if size else 1
        block = size // segment_count
        segments = []
        start = 0
        for index in range(segment_count):
            end = size - 1 if index == segment_count - 1 else start + block - 1
            segments.append({"start": start, "end": end, "downloaded": 0})
            start = end + 1
        return segments

    def _download_segment(
        self,
        url: str,
        part_path: Path,
        segments: list[dict],
        index: int,
        state_path: Path,
    ) -> None:
        segment = segments[index]
        start = segment["start"]
        end = segment["end"]
        failures = 0

        while segment["downloaded"] < end - start + 1:
            if self.cancel_event.is_set():
                return
            offset = start + segment["downloaded"]
            headers = {
                "User-Agent": "MultiThreadDownloader/1.0",
                "Range": f"bytes={offset}-{end}",
            }

            try:
                before = segment["downloaded"]
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.status != 206:
                        raise DownloadError("Server ignored range request during segmented download.")
                    with open(part_path, "r+b", buffering=0) as handle:
                        handle.seek(offset)
                        while not self.cancel_event.is_set():
                            data = response.read(self.chunk_size)
                            if not data:
                                break
                            with self._lock:
                                remaining = end - start + 1 - segment["downloaded"]
                                data = data[:remaining]
                                if not data:
                                    break
                                handle.write(data)
                                segment["downloaded"] += len(data)
                                self._downloaded += len(data)
                                self._report_progress_locked()
                                self._save_state_locked(state_path, url, self._total, segments)
                if segment["downloaded"] == before:
                    raise DownloadError("Connection closed without receiving more data.")
                failures = 0
            except Exception:
                failures += 1
                if failures >= self.retries:
                    raise
                time.sleep(min(2 * failures, 10))

    def _save_state(
        self,
        state_path: Path,
        url: str,
        size: int,
        segments: list[dict],
        force: bool = False,
    ) -> None:
        with self._lock:
            self._save_state_locked(state_path, url, size, segments, force)

    def _save_state_locked(
        self,
        state_path: Path,
        url: str,
        size: int,
        segments: list[dict],
        force: bool = False,
    ) -> None:
        now = time.time()
        if not force and now - self._last_state_save < 1.0:
            return
        self._last_state_save = now
        tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps({"url": url, "size": size, "segments": segments}, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(state_path)

    def _add_progress(self, count: int) -> None:
        with self._lock:
            self._downloaded += count
            self._report_progress_locked()

    def _report_progress(self) -> None:
        with self._lock:
            self._report_progress_locked()

    def _report_progress_locked(self) -> None:
        if self.progress_callback:
            self.progress_callback(self._downloaded, self._total, time.time())

    def _status(self, message: str) -> None:
        if self.status_callback:
            self.status_callback(message)


def _print_progress(downloaded: int, total: int, _timestamp: float) -> None:
    if total:
        percent = downloaded / total * 100
        text = f"\r{percent:6.2f}%  {downloaded / 1024 / 1024:.2f}/{total / 1024 / 1024:.2f} MB"
    else:
        text = f"\r{downloaded / 1024 / 1024:.2f} MB"
    print(text, end="", flush=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Multi-thread HTTP/GitHub downloader.")
    parser.add_argument("url", help="File URL to download.")
    parser.add_argument("-o", "--output", help="Output file name.")
    parser.add_argument("-d", "--directory", default=".", help="Output directory.")
    parser.add_argument("-t", "--threads", type=int, default=8, help="Thread count, 1-32.")
    parser.add_argument("--retries", type=int, default=5, help="Retry count per stream.")
    args = parser.parse_args(argv)

    downloader = MultiThreadDownloader(
        args.url,
        output=args.output,
        directory=args.directory,
        threads=args.threads,
        retries=args.retries,
        progress_callback=_print_progress,
        status_callback=lambda message: print(f"\n{message}", file=sys.stderr),
    )

    try:
        path = downloader.download()
    except KeyboardInterrupt:
        downloader.cancel()
        print("\nCancelled.", file=sys.stderr)
        return 130
    except DownloadError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print(f"\nSaved to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
