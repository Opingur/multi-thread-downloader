from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

from downloader import DownloadError, MultiThreadDownloader


BG = "#fbfaf3"
GRID = "#e9e5d8"
BLUE = "#3a50ff"
INK = "#111111"
MUTED = "#6f6a5c"
LINE = "#d8d2c4"
WHITE = "#fffef8"
GITHUB_URL = "https://github.com/Opingur"
APP_DIR = Path(__file__).resolve().parent
AVATAR_PATH = APP_DIR / "assets" / "opingur-avatar.png"

FONT_MONO = ("Consolas", 10)
FONT_MONO_SMALL = ("Consolas", 8)
FONT_MONO_BOLD = ("Consolas", 10, "bold")
FONT_TITLE = ("Consolas", 36, "bold")
FONT_SERIF = ("Times New Roman", 13)


class PixelButton(tk.Button):
    def __init__(self, master, **kwargs) -> None:
        command = kwargs.pop("command", None)
        super().__init__(
            master,
            command=command,
            bg=WHITE,
            fg=BLUE,
            activebackground=BLUE,
            activeforeground=WHITE,
            disabledforeground="#aaa59a",
            bd=1,
            relief="solid",
            highlightthickness=0,
            padx=14,
            pady=7,
            cursor="hand2",
            font=FONT_MONO_BOLD,
            **kwargs,
        )


class PixelProgress(tk.Canvas):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(
            master,
            height=20,
            bg=BG,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self.percent = 0.0
        self.bind("<Configure>", lambda _event: self._draw())

    def set_value(self, percent: float) -> None:
        self.percent = max(0.0, min(percent, 100.0))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        self.create_rectangle(0, 0, width - 1, height - 1, outline=INK, fill=WHITE)

        fill_width = int((width - 2) * self.percent / 100)
        if fill_width > 0:
            self.create_rectangle(1, 1, fill_width, height - 2, outline=BLUE, fill=BLUE)

        for x in range(8, width, 8):
            self.create_line(x, 1, x, height - 2, fill="#e4dfd1")


class DotCanvas(tk.Canvas):
    def __init__(self, master, bottom_dash: bool = False, **kwargs) -> None:
        super().__init__(master, bg=BG, highlightthickness=0, bd=0, **kwargs)
        self.bottom_dash = bottom_dash
        self.bind("<Configure>", lambda _event: self._draw())

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        for y in range(8, height, 12):
            for x in range(8, width, 12):
                self.create_rectangle(x, y, x + 1, y + 1, outline=GRID, fill=GRID)
        if self.bottom_dash:
            self.create_line(0, height - 2, width, height - 2, fill=BLUE, dash=(2, 4), width=2)


class DownloadApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Multi-thread Downloader")
        self.overrideredirect(True)
        self.geometry("900x560")
        self.minsize(760, 500)
        self.configure(bg=BG)
        self.attributes("-alpha", 0.98)
        self.bind("<Map>", self._restore_borderless)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.downloader: MultiThreadDownloader | None = None
        self.worker: threading.Thread | None = None
        self._drag_start: tuple[int, int] | None = None
        self._avatar_image: tk.PhotoImage | None = None
        self._about_window: tk.Toplevel | None = None
        self.started_at = 0.0
        self.last_bytes = 0
        self.last_time = 0.0

        self.url_var = tk.StringVar()
        self.dir_var = tk.StringVar(value=str(Path.cwd()))
        self.name_var = tk.StringVar()
        self.thread_var = tk.IntVar(value=8)
        self.status_var = tk.StringVar(value="READY")
        self.detail_var = tk.StringVar(value="WAITING FOR A DOWNLOAD URL")
        self.saved_var = tk.StringVar(value="")

        self._build_ui()
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_topbar()
        self._build_edge_glow()
        self._build_hero()
        self._build_form()
        self._build_bottom_glow()

    def _build_topbar(self) -> None:
        topbar = tk.Frame(self, bg=BG, height=42, highlightbackground=LINE, highlightthickness=1)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.columnconfigure(1, weight=1)
        self._bind_drag(topbar)

        github_link = tk.Label(
            topbar,
            text="[] OPINGUR / GITHUB",
            bg=BG,
            fg=BLUE,
            font=FONT_MONO_BOLD,
            cursor="hand2",
        )
        github_link.grid(row=0, column=0, sticky="w", padx=20)
        github_link.bind("<Button-1>", lambda _event: self._open_github())
        self._bind_drag(github_link)

        about = tk.Label(
            topbar,
            text="ABOUT US",
            bg=BG,
            fg=INK,
            font=FONT_MONO_BOLD,
            cursor="hand2",
        )
        about.grid(row=0, column=1)
        about.bind("<Button-1>", lambda _event: self._show_about())
        self._bind_drag(about)

        nav = tk.Frame(topbar, bg=BG)
        nav.grid(row=0, column=2, sticky="e", padx=12)
        self._bind_drag(nav)
        for text in ("URL", "OUTPUT", "THREADS", "STATUS"):
            label = tk.Label(nav, text=text, bg=BG, fg=INK, font=FONT_MONO_SMALL)
            label.pack(side="left", padx=14)
            self._bind_drag(label)

        window_controls = tk.Frame(topbar, bg=BG)
        window_controls.grid(row=0, column=3, sticky="e", padx=(0, 16))
        self._bind_drag(window_controls)

        tk.Label(
            window_controls,
            text="_",
            bg=WHITE,
            fg=INK,
            font=FONT_MONO_BOLD,
            width=3,
            height=1,
            highlightbackground=LINE,
            highlightthickness=1,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        window_controls.winfo_children()[0].bind("<Button-1>", lambda _event: self._minimize())

        tk.Label(
            window_controls,
            text="X",
            bg=WHITE,
            fg=INK,
            font=FONT_MONO_BOLD,
            width=3,
            height=1,
            highlightbackground=LINE,
            highlightthickness=1,
            cursor="hand2",
        ).pack(side="left")
        window_controls.winfo_children()[1].bind("<Button-1>", lambda _event: self.destroy())

    def _build_edge_glow(self) -> None:
        glow = tk.Canvas(self, height=24, bg=BG, highlightthickness=0, bd=0)
        glow.grid(row=1, column=0, sticky="ew")
        glow.bind("<Configure>", lambda event: self._draw_edge_glow(glow, event.width, event.height))

    def _build_bottom_glow(self) -> None:
        glow = tk.Canvas(self, height=28, bg=BG, highlightthickness=0, bd=0)
        glow.grid(row=4, column=0, sticky="ew")
        glow.bind("<Configure>", lambda event: self._draw_bottom_glow(glow, event.width, event.height))

    @staticmethod
    def _draw_edge_glow(canvas: tk.Canvas, width: int, height: int) -> None:
        canvas.delete("all")
        colors = ("#ffffff", "#f4fbff", "#e7f5ff", "#d6edff", "#c6e5ff")
        stripe = max(1, height // len(colors))
        for index, color in enumerate(colors):
            y0 = index * stripe
            y1 = height if index == len(colors) - 1 else (index + 1) * stripe
            canvas.create_rectangle(0, y0, width, y1, outline=color, fill=color)

    @staticmethod
    def _draw_bottom_glow(canvas: tk.Canvas, width: int, height: int) -> None:
        canvas.delete("all")
        colors = ("#fbfaf3", "#f0f8ff", "#e0f1ff", "#d2eaff", "#c4e3ff")
        stripe = max(1, height // len(colors))
        for index, color in enumerate(colors):
            y0 = index * stripe
            y1 = height if index == len(colors) - 1 else (index + 1) * stripe
            canvas.create_rectangle(0, y0, width, y1, outline=color, fill=color)

    def _build_hero(self) -> None:
        hero = DotCanvas(self, height=178, bottom_dash=True)
        hero.grid(row=2, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)

        title = tk.Label(
            hero,
            text="MULTI THREAD\nDOWNLOADER",
            bg=BG,
            fg=BLUE,
            font=FONT_TITLE,
            justify="left",
            anchor="w",
        )
        title.place(x=20, y=14)

        subtitle = tk.Label(
            hero,
            text="Fast segmented HTTP downloads. GitHub release links keep their original file suffix.",
            bg=BG,
            fg=INK,
            font=FONT_SERIF,
            anchor="w",
        )
        subtitle.place(x=22, y=132)

    def _build_form(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.grid(row=3, column=0, sticky="nsew", padx=20, pady=20)
        body.columnconfigure(1, weight=1)

        self._label(body, "DOWNLOAD URL").grid(row=0, column=0, sticky="nw", pady=(0, 8))
        self.url_entry = self._entry(body, self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 14))

        self._label(body, "SAVE TO").grid(row=1, column=0, sticky="nw", pady=(0, 8))
        self.dir_entry = self._entry(body, self.dir_var)
        self.dir_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 14))
        self.browse_button = PixelButton(body, text="BROWSE", command=self._browse_directory)
        self.browse_button.grid(row=1, column=3, sticky="ew", padx=(12, 0), pady=(0, 14))

        self._label(body, "FILE NAME").grid(row=2, column=0, sticky="nw", pady=(0, 8))
        self.name_entry = self._entry(body, self.name_var)
        self.name_entry.grid(row=2, column=1, sticky="ew", pady=(0, 14))

        self._label(body, "THREADS").grid(row=2, column=2, sticky="e", padx=(18, 10), pady=(0, 14))
        self.thread_spin = tk.Spinbox(
            body,
            from_=1,
            to=32,
            textvariable=self.thread_var,
            width=6,
            bg=WHITE,
            fg=INK,
            buttonbackground=WHITE,
            insertbackground=BLUE,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=BLUE,
            highlightbackground=INK,
            font=FONT_MONO_BOLD,
            justify="center",
        )
        self.thread_spin.grid(row=2, column=3, sticky="ew", pady=(0, 14))

        separator = tk.Canvas(body, height=28, bg=BG, highlightthickness=0, bd=0)
        separator.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 8))
        separator.bind(
            "<Configure>",
            lambda event: self._draw_blue_dashes(separator, event.width),
        )

        self._label(body, "CURRENT PROGRESS").grid(row=4, column=0, sticky="nw", pady=(4, 12))
        self.progress = PixelProgress(body)
        self.progress.grid(row=4, column=1, columnspan=3, sticky="ew", pady=(4, 12))

        self._label(body, "STATUS").grid(row=5, column=0, sticky="nw", pady=(4, 0))
        status_box = tk.Frame(body, bg=BG)
        status_box.grid(row=5, column=1, columnspan=3, sticky="ew", pady=(4, 0))
        status_box.columnconfigure(0, weight=1)

        tk.Label(
            status_box,
            textvariable=self.status_var,
            bg=BG,
            fg=BLUE,
            font=FONT_MONO_BOLD,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            status_box,
            textvariable=self.detail_var,
            bg=BG,
            fg=INK,
            font=FONT_MONO,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        tk.Label(
            status_box,
            textvariable=self.saved_var,
            bg=BG,
            fg=MUTED,
            font=FONT_MONO_SMALL,
            anchor="w",
            wraplength=640,
            justify="left",
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0))

        actions = tk.Frame(body, bg=BG)
        actions.grid(row=6, column=0, columnspan=4, sticky="e", pady=(28, 0))
        self.start_button = PixelButton(actions, text="START DOWNLOAD", command=self._start)
        self.start_button.pack(side="left", padx=(0, 10))
        self.cancel_button = PixelButton(actions, text="CANCEL", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left")

    def _label(self, master, text: str) -> tk.Label:
        return tk.Label(master, text=text, bg=BG, fg=BLUE, font=FONT_MONO_SMALL, anchor="w")

    def _entry(self, master, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            master,
            textvariable=variable,
            bg=WHITE,
            fg=INK,
            insertbackground=BLUE,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=BLUE,
            highlightbackground=INK,
            font=FONT_MONO,
        )

    @staticmethod
    def _draw_blue_dashes(canvas: tk.Canvas, width: int) -> None:
        canvas.delete("all")
        canvas.create_line(0, 14, width, 14, fill=BLUE, dash=(2, 4), width=2)

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<Button-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._drag_window, add="+")

    def _start_drag(self, event) -> None:
        self._drag_start = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_window(self, event) -> None:
        if not self._drag_start:
            return
        offset_x, offset_y = self._drag_start
        self.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _minimize(self) -> None:
        self.overrideredirect(False)
        self.iconify()

    def _restore_borderless(self, _event=None) -> None:
        if self.state() == "normal":
            self.after(10, lambda: self.overrideredirect(True))

    def _open_github(self) -> None:
        webbrowser.open(GITHUB_URL)

    def _show_about(self) -> None:
        if self._about_window and self._about_window.winfo_exists():
            self._about_window.lift()
            return

        dialog = tk.Toplevel(self)
        self._about_window = dialog
        dialog.overrideredirect(True)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.attributes("-alpha", 0.98)
        dialog.geometry(self._center_geometry(620, 390))

        shell = tk.Frame(dialog, bg=BG, highlightbackground=INK, highlightthickness=1)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)

        titlebar = tk.Frame(shell, bg=BG, height=36, highlightbackground=LINE, highlightthickness=1)
        titlebar.grid(row=0, column=0, sticky="ew")
        titlebar.grid_propagate(False)
        titlebar.columnconfigure(0, weight=1)

        tk.Label(
            titlebar,
            text="ABOUT US",
            bg=BG,
            fg=BLUE,
            font=FONT_MONO_BOLD,
        ).grid(row=0, column=0, sticky="w", padx=16)

        close = tk.Label(
            titlebar,
            text="X",
            bg=WHITE,
            fg=INK,
            font=FONT_MONO_BOLD,
            width=3,
            highlightbackground=LINE,
            highlightthickness=1,
            cursor="hand2",
        )
        close.grid(row=0, column=1, padx=14)
        close.bind("<Button-1>", lambda _event: dialog.destroy())

        for widget in (titlebar,):
            widget.bind("<Button-1>", lambda event: self._start_dialog_drag(dialog, event), add="+")
            widget.bind("<B1-Motion>", lambda event: self._drag_dialog(dialog, event), add="+")

        content = DotCanvas(shell, height=354)
        content.grid(row=1, column=0, sticky="nsew")

        tk.Label(
            content,
            text="OPINGUR",
            bg=BG,
            fg=BLUE,
            font=("Consolas", 28, "bold"),
        ).place(x=38, y=42)
        tk.Label(
            content,
            text="Multi-thread Downloader author",
            bg=BG,
            fg=INK,
            font=FONT_SERIF,
        ).place(x=40, y=96)
        tk.Label(
            content,
            text="If this downloader helps, visit the GitHub homepage.",
            bg=BG,
            fg=MUTED,
            font=FONT_MONO,
        ).place(x=40, y=140)

        link = tk.Label(
            content,
            text=GITHUB_URL,
            bg=BG,
            fg=BLUE,
            font=FONT_MONO_BOLD,
            cursor="hand2",
        )
        link.place(x=40, y=174)
        link.bind("<Button-1>", lambda _event: self._open_github())

        PixelButton(content, text="STAR ON GITHUB", command=self._open_github).place(x=40, y=230)
        PixelButton(content, text="CLOSE", command=dialog.destroy).place(x=205, y=230)

        avatar_frame = tk.Frame(content, bg=WHITE, highlightbackground=INK, highlightthickness=1)
        avatar_frame.place(x=432, y=58, width=140, height=140)
        avatar = self._load_avatar()
        if avatar:
            tk.Label(avatar_frame, image=avatar, bg=WHITE).place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(
                avatar_frame,
                text="NO AVATAR",
                bg=WHITE,
                fg=MUTED,
                font=FONT_MONO,
            ).place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            content,
            text="ABOUT / GITHUB / AUTHOR",
            bg=BG,
            fg=BLUE,
            font=FONT_MONO_SMALL,
        ).place(x=40, y=310)

    def _center_geometry(self, width: int, height: int) -> str:
        self.update_idletasks()
        x = self.winfo_x() + max((self.winfo_width() - width) // 2, 0)
        y = self.winfo_y() + max((self.winfo_height() - height) // 2, 0)
        return f"{width}x{height}+{x}+{y}"

    def _load_avatar(self) -> tk.PhotoImage | None:
        if self._avatar_image:
            return self._avatar_image
        if not AVATAR_PATH.exists():
            return None
        image = tk.PhotoImage(file=str(AVATAR_PATH))
        scale = max(1, image.width() // 124, image.height() // 124)
        self._avatar_image = image.subsample(scale, scale)
        return self._avatar_image

    def _start_dialog_drag(self, dialog: tk.Toplevel, event) -> None:
        dialog._drag_start = (event.x_root - dialog.winfo_x(), event.y_root - dialog.winfo_y())

    def _drag_dialog(self, dialog: tk.Toplevel, event) -> None:
        offset_x, offset_y = getattr(dialog, "_drag_start", (0, 0))
        dialog.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _browse_directory(self) -> None:
        path = filedialog.askdirectory(initialdir=self.dir_var.get() or str(Path.cwd()))
        if path:
            self.dir_var.set(path)

    def _start(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            self.status_var.set("URL REQUIRED")
            self.detail_var.set("Paste an http:// or https:// file link before starting.")
            self.saved_var.set("")
            return

        directory = self.dir_var.get().strip() or str(Path.cwd())
        output = self.name_var.get().strip() or None
        try:
            threads = max(1, min(int(self.thread_var.get()), 32))
        except tk.TclError:
            threads = 8
            self.thread_var.set(threads)

        self.started_at = time.time()
        self.last_time = self.started_at
        self.last_bytes = 0
        self.progress.set_value(0)
        self.detail_var.set("Preparing remote file metadata...")
        self.saved_var.set("")
        self.status_var.set("STARTING")
        self.start_button.config(state="disabled")
        self.cancel_button.config(state="normal")

        self.downloader = MultiThreadDownloader(
            url,
            output=output,
            directory=directory,
            threads=threads,
            progress_callback=self._on_progress,
            status_callback=self._on_status,
        )
        self.worker = threading.Thread(target=self._run_download, daemon=True)
        self.worker.start()

    def _cancel(self) -> None:
        if self.downloader:
            self.downloader.cancel()
            self.status_var.set("CANCELLING")
            self.cancel_button.config(state="disabled")

    def _run_download(self) -> None:
        assert self.downloader is not None
        try:
            path = self.downloader.download()
            self.events.put(("done", str(path)))
        except DownloadError as exc:
            self.events.put(("error", str(exc)))
        except Exception as exc:
            self.events.put(("error", f"Unexpected error: {exc}"))

    def _on_progress(self, downloaded: int, total: int, timestamp: float) -> None:
        self.events.put(("progress", downloaded, total, timestamp))

    def _on_status(self, message: str) -> None:
        self.events.put(("status", message))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self._apply_progress(event[1], event[2], event[3])
                elif kind == "status":
                    self.status_var.set(event[1].upper())
                elif kind == "done":
                    self._finish()
                    self.progress.set_value(0)
                    self.last_bytes = 0
                    self.status_var.set("READY")
                    self.detail_var.set("Download complete. Progress reset for the next file.")
                    self.saved_var.set(f"SAVED TO: {event[1]}")
                elif kind == "error":
                    self._finish()
                    self.status_var.set("DOWNLOAD STOPPED")
                    self.saved_var.set("")
                    self.progress.set_value(0)
                    messagebox.showerror("Download error", event[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _apply_progress(self, downloaded: int, total: int, timestamp: float) -> None:
        if total:
            self.progress.set_value(min(downloaded / total * 100, 100))
        now = timestamp
        elapsed = max(now - self.last_time, 0.001)
        speed = (downloaded - self.last_bytes) / elapsed
        self.last_bytes = downloaded
        self.last_time = now
        total_text = self._format_bytes(total) if total else "UNKNOWN"
        self.detail_var.set(
            f"{self._format_bytes(downloaded)} / {total_text}    {self._format_bytes(speed)}/S"
        )

    def _finish(self) -> None:
        self.start_button.config(state="normal")
        self.cancel_button.config(state="disabled")
        self.downloader = None
        self.worker = None

    @staticmethod
    def _format_bytes(value: float) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"


if __name__ == "__main__":
    DownloadApp().mainloop()
