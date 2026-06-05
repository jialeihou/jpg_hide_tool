#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JPG 文件隐藏工具
功能：
1. 将任意类型、多个文件隐藏到 JPG 图片尾部；
2. 隐藏后 JPG 仍可正常打开；
3. 可从 JPG 中释放文件，并恢复原文件名和后缀；
4. 仅使用 Python 标准库，适合内网、麒麟 Linux、macOS 环境；
5. 提供 HTML 前台页面调用。

说明：
- 本工具不是加密工具，只是文件隐写/附加封装。如需保密，请先对待隐藏文件自行加密。
- 原理是在 JPG 文件末尾追加自定义数据块。绝大多数图片查看器会忽略 JPG 结束标记后的附加内容。
"""

from __future__ import annotations

import html
import io
import json
import os
import shutil
import socket
import struct
import sys
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
EXTRACT_DIR = BASE_DIR / "extracted"

for d in (UPLOAD_DIR, OUTPUT_DIR, EXTRACT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 自定义隐藏数据格式：
# JPG原始内容 + MAGIC + version(1 byte) + meta_len(4 bytes big-endian) + meta_json + zip_payload + zip_len(8 bytes big-endian) + MAGIC_END
MAGIC = b"JPG_HIDE_TOOL_V1_START"
MAGIC_END = b"JPG_HIDE_TOOL_V1_END__"
VERSION = 1
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB，可按需调整


def safe_name(name: str) -> str:
    """清理文件名，避免路径穿越。保留中文、空格和常见符号。"""
    name = os.path.basename(name.replace("\\", "/"))
    if not name:
        return f"file_{int(time.time())}"
    bad_chars = '<>:"|?*\x00'
    cleaned = "".join("_" if c in bad_chars else c for c in name)
    return cleaned.strip() or f"file_{int(time.time())}"


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = safe_name(filename)
    target = directory / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    i = 1
    while True:
        candidate = directory / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def is_jpg_file(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(2)
    return head == b"\xff\xd8"


def create_payload_zip(file_paths: list[Path]) -> tuple[bytes, dict]:
    """把多个文件打成内存 zip，并返回元数据。"""
    meta_files = []
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for p in file_paths:
            original_name = safe_name(p.name)
            arcname = original_name
            if arcname in used_names:
                stem = Path(original_name).stem
                suffix = Path(original_name).suffix
                idx = 1
                while f"{stem}_{idx}{suffix}" in used_names:
                    idx += 1
                arcname = f"{stem}_{idx}{suffix}"
            used_names.add(arcname)
            zf.write(p, arcname=arcname)
            meta_files.append({
                "filename": arcname,
                "size": p.stat().st_size,
                "mtime": int(p.stat().st_mtime),
            })
    meta = {
        "tool": "jpg_hide_tool",
        "version": VERSION,
        "created_at": int(time.time()),
        "file_count": len(meta_files),
        "files": meta_files,
    }
    return bio.getvalue(), meta


def hide_files_into_jpg(jpg_path: Path, files_to_hide: list[Path], out_name: str | None = None) -> Path:
    if not jpg_path.exists():
        raise ValueError("JPG 文件不存在")
    if not is_jpg_file(jpg_path):
        raise ValueError("请选择真正的 JPG/JPEG 文件")
    if not files_to_hide:
        raise ValueError("至少选择一个需要隐藏的文件")

    payload_zip, meta = create_payload_zip(files_to_hide)
    meta_json = json.dumps(meta, ensure_ascii=False).encode("utf-8")

    if out_name:
        out_filename = safe_name(out_name)
        if not out_filename.lower().endswith((".jpg", ".jpeg")):
            out_filename += ".jpg"
    else:
        out_filename = f"{jpg_path.stem}_hidden.jpg"

    out_path = unique_path(OUTPUT_DIR, out_filename)
    with jpg_path.open("rb") as src, out_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.write(MAGIC)
        dst.write(struct.pack(">B", VERSION))
        dst.write(struct.pack(">I", len(meta_json)))
        dst.write(meta_json)
        dst.write(payload_zip)
        dst.write(struct.pack(">Q", len(payload_zip)))
        dst.write(MAGIC_END)
    return out_path


def find_payload_block(data: bytes) -> tuple[dict, bytes]:
    """从 JPG 二进制中定位隐藏数据并返回 meta 与 zip payload。"""
    if not data.endswith(MAGIC_END):
        raise ValueError("未发现隐藏数据标记，或文件不是本工具生成的隐藏 JPG")

    end_pos = len(data) - len(MAGIC_END)
    if end_pos < 8:
        raise ValueError("隐藏数据结构不完整")

    zip_len = struct.unpack(">Q", data[end_pos - 8:end_pos])[0]
    zip_start = end_pos - 8 - zip_len
    if zip_start < 0:
        raise ValueError("隐藏数据长度异常")

    # 在 zip_start 前寻找最后一个 MAGIC，避免原图中偶然出现同样字节
    start_pos = data.rfind(MAGIC, 0, zip_start)
    if start_pos < 0:
        raise ValueError("未找到隐藏数据起始标记")

    cursor = start_pos + len(MAGIC)
    version = struct.unpack(">B", data[cursor:cursor + 1])[0]
    cursor += 1
    if version != VERSION:
        raise ValueError(f"隐藏数据版本不兼容：{version}")

    meta_len = struct.unpack(">I", data[cursor:cursor + 4])[0]
    cursor += 4
    meta_json = data[cursor:cursor + meta_len]
    cursor += meta_len

    if cursor != zip_start:
        raise ValueError("隐藏数据结构校验失败")

    meta = json.loads(meta_json.decode("utf-8"))
    payload_zip = data[zip_start:zip_start + zip_len]
    return meta, payload_zip


def extract_files_from_jpg(hidden_jpg_path: Path) -> Path:
    if not hidden_jpg_path.exists():
        raise ValueError("文件不存在")
    data = hidden_jpg_path.read_bytes()
    meta, payload_zip = find_payload_block(data)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = unique_path(EXTRACT_DIR, f"extract_{hidden_jpg_path.stem}_{timestamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(payload_zip), "r") as zf:
        for info in zf.infolist():
            filename = safe_name(info.filename)
            target = unique_path(out_dir, filename)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    (out_dir / "hidden_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir


def parse_multipart_form(content_type: str, body: bytes) -> dict[str, list[tuple[str, bytes]]]:
    """极简 multipart/form-data 解析器，替代 Python 3.13 移除的 cgi 模块。"""
    if "multipart/form-data" not in content_type:
        return {}
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("表单 boundary 缺失")
    boundary = content_type.split(marker, 1)[1].strip()
    if boundary.startswith('"') and boundary.endswith('"'):
        boundary = boundary[1:-1]
    boundary_bytes = ("--" + boundary).encode("utf-8")

    result: dict[str, list[tuple[str, bytes]]] = {}
    parts = body.split(boundary_bytes)
    for part in parts:
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        part = part.strip(b"\r\n")
        if part.endswith(b"--"):
            part = part[:-2].strip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", errors="replace").split("\r\n")
        disposition = ""
        for h in headers:
            if h.lower().startswith("content-disposition:"):
                disposition = h
                break
        if not disposition:
            continue
        attrs = {}
        for item in disposition.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                attrs[k.strip().lower()] = v.strip().strip('"')
        field_name = attrs.get("name")
        if not field_name:
            continue
        filename = attrs.get("filename", "")
        # 浏览器会在文件内容末尾带 CRLF，multipart split 后这里通常已经不含边界 CRLF，但保守处理一次
        if content.endswith(b"\r\n"):
            content = content[:-2]
        result.setdefault(field_name, []).append((filename, content))
    return result


def save_uploaded_files(items: list[tuple[str, bytes]], subdir: str) -> list[Path]:
    saved = []
    target_dir = UPLOAD_DIR / subdir / time.strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in items:
        if not filename or len(content) == 0:
            continue
        path = unique_path(target_dir, filename)
        path.write_bytes(content)
        saved.append(path)
    return saved


def page(message: str = "", result_html: str = "") -> bytes:
    msg = f'<div class="msg">{html.escape(message)}</div>' if message else ""
    body = f"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JPG 文件隐藏工具</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif; background:#f4f7fb; color:#1f2937; }}
.container {{ max-width:1080px; margin:36px auto; padding:0 20px; }}
.header {{ background:linear-gradient(135deg,#0f4c81,#2c7be5); color:white; border-radius:18px; padding:28px 32px; box-shadow:0 14px 34px rgba(31,77,135,.2); }}
.header h1 {{ margin:0 0 8px; font-size:28px; }}
.header p {{ margin:0; opacity:.92; line-height:1.7; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:22px; }}
.card {{ background:white; border-radius:18px; padding:24px; box-shadow:0 8px 24px rgba(15,23,42,.08); }}
h2 {{ margin:0 0 16px; font-size:20px; }}
label {{ display:block; font-weight:600; margin:14px 0 8px; }}
input[type=file], input[type=text] {{ width:100%; box-sizing:border-box; padding:10px; border:1px solid #d1d5db; border-radius:10px; background:#fff; }}
button {{ margin-top:18px; padding:12px 18px; border:0; border-radius:12px; background:#2563eb; color:white; font-weight:700; cursor:pointer; }}
button:hover {{ background:#1d4ed8; }}
.note {{ font-size:13px; color:#6b7280; line-height:1.7; margin-top:12px; }}
.msg {{ margin-top:20px; padding:14px 16px; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:12px; color:#065f46; }}
.result {{ margin-top:20px; padding:18px; background:white; border-radius:16px; box-shadow:0 8px 24px rgba(15,23,42,.08); line-height:1.8; }}
a {{ color:#1d4ed8; text-decoration:none; font-weight:700; }}
ul {{ margin-top:8px; }}
@media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>JPG 文件隐藏工具</h1>
    <p>支持将多个任意类型文件隐藏到 JPG 中，隐藏后图片仍可打开；也可释放隐藏文件并恢复原文件名和后缀。仅使用 Python 标准库。</p>
  </div>
  {msg}
  <div class="grid">
    <div class="card">
      <h2>一、隐藏文件到 JPG</h2>
      <form action="/hide" method="post" enctype="multipart/form-data">
        <label>选择原始 JPG/JPEG 图片</label>
        <input type="file" name="jpg" accept=".jpg,.jpeg,image/jpeg" required>
        <label>选择要隐藏的文件，可多选</label>
        <input type="file" name="files" multiple required>
        <label>输出文件名，可选</label>
        <input type="text" name="out_name" placeholder="例如：工作图片_hidden.jpg">
        <button type="submit">生成隐藏 JPG</button>
      </form>
      <div class="note">提示：不要用图片压缩软件重新压缩生成后的 JPG，否则隐藏数据可能丢失。</div>
    </div>
    <div class="card">
      <h2>二、释放隐藏文件</h2>
      <form action="/extract" method="post" enctype="multipart/form-data">
        <label>选择已经隐藏文件的 JPG</label>
        <input type="file" name="hidden_jpg" accept=".jpg,.jpeg,image/jpeg" required>
        <button type="submit">释放文件</button>
      </form>
      <div class="note">释放结果会保存在程序目录 extracted 文件夹下，可在页面下载，也可直接打开该目录查看。</div>
    </div>
  </div>
  {result_html}
</div>
</body>
</html>
"""
    return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "JpgHideTool/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def send_html(self, content: bytes, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(page())
            return
        if parsed.path == "/download":
            qs = parse_qs(parsed.query)
            path_str = qs.get("path", [""])[0]
            try:
                target = Path(path_str).resolve()
                allowed_roots = [OUTPUT_DIR.resolve(), EXTRACT_DIR.resolve()]
                if not any(str(target).startswith(str(root)) for root in allowed_roots):
                    raise ValueError("非法下载路径")
                if target.is_dir():
                    zip_path = unique_path(OUTPUT_DIR, f"{target.name}.zip")
                    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for p in target.rglob("*"):
                            if p.is_file():
                                zf.write(p, arcname=str(p.relative_to(target)))
                    target = zip_path
                if not target.exists() or not target.is_file():
                    raise ValueError("文件不存在")
                content = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(target.name)}")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_html(page(f"下载失败：{e}"), HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def read_form(self) -> dict[str, list[tuple[str, bytes]]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_SIZE:
            raise ValueError("上传内容超过限制")
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        return parse_multipart_form(content_type, body)

    def do_POST(self):
        try:
            if self.path == "/hide":
                form = self.read_form()
                jpgs = save_uploaded_files(form.get("jpg", []), "jpg")
                files = save_uploaded_files(form.get("files", []), "payload")
                out_name_items = form.get("out_name", [])
                out_name = ""
                if out_name_items:
                    out_name = out_name_items[0][1].decode("utf-8", errors="ignore").strip()
                if not jpgs:
                    raise ValueError("未上传 JPG 文件")
                if not files:
                    raise ValueError("未上传需要隐藏的文件")
                out_path = hide_files_into_jpg(jpgs[0], files, out_name or None)
                link = f'/download?path={quote(str(out_path))}'
                result = f'<div class="result"><b>生成成功：</b>{html.escape(out_path.name)}<br><a href="{link}">下载隐藏后的 JPG</a><br><span class="note">文件位置：{html.escape(str(out_path))}</span></div>'
                self.send_html(page("隐藏文件完成。", result))
                return

            if self.path == "/extract":
                form = self.read_form()
                jpgs = save_uploaded_files(form.get("hidden_jpg", []), "hidden_jpg")
                if not jpgs:
                    raise ValueError("未上传隐藏 JPG 文件")
                out_dir = extract_files_from_jpg(jpgs[0])
                files_li = "".join(f"<li>{html.escape(p.name)}</li>" for p in out_dir.iterdir() if p.is_file() and p.name != "hidden_meta.json")
                link = f'/download?path={quote(str(out_dir))}'
                result = f'<div class="result"><b>释放成功：</b><br><ul>{files_li}</ul><a href="{link}">下载释放结果 ZIP</a><br><span class="note">释放目录：{html.escape(str(out_dir))}</span></div>'
                self.send_html(page("释放隐藏文件完成。", result))
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        except Exception as e:
            self.send_html(page(f"处理失败：{e}"), HTTPStatus.BAD_REQUEST)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    host = "127.0.0.1"
    port = 8765
    if len(sys.argv) >= 2:
        port = int(sys.argv[1])
    server = ThreadingHTTPServer((host, port), Handler)
    print("=" * 64)
    print("JPG 文件隐藏工具已启动")
    print(f"本机访问：http://127.0.0.1:{port}/")
    print(f"局域网 IP 参考：{get_local_ip()}，如需局域网访问请修改 app.py host 为 0.0.0.0")
    print("按 Ctrl+C 退出")
    print("=" * 64)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
