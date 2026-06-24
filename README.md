# 多线程下载器

一个无第三方依赖的 Python 多线程 HTTP 下载器，适合下载 GitHub Release、直链文件和其他支持 `Range` 分段请求的文件。

## 图形界面

双击 `start.bat`，或在当前目录运行：

```powershell
python main.py
```

填写 URL、保存目录、线程数后点击 `Start`。中途取消后会保留 `.part` 和 `.state.json`，再次下载同一个 URL 到同一个文件名会自动断点续传。

文件名留空时会自动从 URL 或服务器响应里识别原始文件名和后缀，例如 `.exe`、`.zip`。如果手动填写的文件名没有后缀，会自动补上识别到的后缀。

## 命令行

```powershell
python downloader.py "https://github.com/user/project/releases/download/v1.0/file.zip" -d D:\Downloads -t 16
```

常用参数：

- `-o, --output`：指定保存文件名。
- `-d, --directory`：指定保存目录。
- `-t, --threads`：线程数，范围 1 到 32。
- `--retries`：每个分段的重试次数。

## 说明

- 服务器支持 `Accept-Ranges: bytes` 且能返回文件大小时，会自动启用多线程分段下载。
- 如果服务器不支持分段，会自动降级为单线程下载。
- GitHub 下载链接经常会重定向，程序会跟随重定向并使用最终文件名。
- 断点续传依赖同目录下的 `.part` 和 `.state.json` 临时文件，下载完成后会自动清理。
