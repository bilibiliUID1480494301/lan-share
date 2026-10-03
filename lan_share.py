#!/usr/bin/env python3
"""lan-share -- share a folder over your LAN with one command.

A zero-dependency file server built on Python's http.server:
browse, download and upload files from any device on the same network.

    python lan_share.py --dir ./share --port 8000

Licensed under the MIT License.
"""
from __future__ import annotations

import argparse
import email.parser
import email.policy
import http.server
import json
import mimetypes
import os
import re
import socket
import socketserver
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

__version__ = "0.2.0"

UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lan-share - {path}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c1e21}}
 header{{background:#1f6feb;color:#fff;padding:14px 18px}}
 main{{max-width:820px;margin:0 auto;padding:12px}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
 td,th{{padding:9px 12px;text-align:left;border-bottom:1px solid #eceff3;font-size:14px;word-break:break-all}}
 th{{background:#fafbfc;color:#57606a;font-weight:600}}
 a{{color:#1f6feb;text-decoration:none}} a:hover{{text-decoration:underline}}
 .upload{{margin:14px 0;padding:12px;background:#fff;border:1px dashed #d0d7de;border-radius:8px}}
 button{{background:#1f6feb;color:#fff;border:0;border-radius:6px;padding:7px 14px;cursor:pointer}}
 .hint{{color:#57606a;font-size:12px;margin-top:6px}}
</style>
</head>
<body>
<header><b>lan-share</b> &mdash; {path}</header>
<main>
{upload}
<table>
<tr><th>Name</th><th style="width:110px">Size</th><th style="width:170px">Modified</th></tr>
{rows}
</table>
<p class="hint">lan-share {version} &middot; zero-dependency LAN file server</p>
</main>
</body></html>"""


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def lan_ip() -> str:
    """Best-effort LAN address (no packets are actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class ShareServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """HTTP server carrying the shared-folder configuration."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, *, root, read_only=False, token=None, max_mb=512):
        super().__init__(addr, handler)
        self.root = Path(root).resolve()
        self.read_only = read_only
        self.token = token
        self.max_bytes = int(max_mb) * 1024 * 1024


class ShareHandler(http.server.BaseHTTPRequestHandler):
    server: ShareServer

    # ---- plumbing ----------------------------------------------------
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _authorized(self) -> bool:
        token = self.server.token
        if not token:
            return True
        query = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(query).get("token", [""])[0] == token

    def _resolve(self, url_path: str):
        """Map a URL path inside the shared root; None when it escapes."""
        rel = urllib.parse.unquote(urllib.parse.urlparse(url_path).path)
        rel = rel.replace("\\", "/").lstrip("/")
        if rel in ("", "."):
            return self.server.root
        try:
            candidate = (self.server.root / rel).resolve()
        except (OSError, ValueError):
            return None
        if candidate != self.server.root and self.server.root not in candidate.parents:
            return None
        return candidate

    def _link(self, name: str, is_dir: bool = False) -> str:
        href = urllib.parse.quote(name) + ("/" if is_dir else "")
        if self.server.token:
            href += "&" if "?" in href else "?"
            href += "token=" + urllib.parse.quote(self.server.token)
        return href

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self, count: int) -> None:
        remaining = count
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)

    # ---- GET ----------------------------------------------------------
    def do_GET(self) -> None:
        if not self._authorized():
            self.send_error(401, "Token required", "append ?token=... to the URL")
            return
        target = self._resolve(self.path)
        if target is None:
            self.send_error(403, "Forbidden", "path escapes the shared root")
            return
        if target.is_dir():
            self._send_html(self._render_dir(target))
        elif target.is_file():
            self._send_file(target)
        else:
            self.send_error(404, "Not found")

    def _render_dir(self, folder: Path) -> str:
        try:
            entries = sorted(
                folder.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except (PermissionError, OSError):
            entries = []
        rows = []
        if folder != self.server.root:
            rows.append(
                '<tr><td><a href="{0}">&#8617; root</a></td><td>&mdash;</td><td>&mdash;</td></tr>'
                .format(self._link("", True))
            )
        shown = 0
        for entry in entries:
            if shown >= 2000:
                rows.append('<tr><td colspan="3">&hellip; too many entries</td></tr>')
                break
            name = entry.name
            if entry.is_dir():
                rows.append(
                    f'<tr><td><a href="{self._link(name, True)}">&#128193; {name}/</a></td>'
                    "<td>&mdash;</td><td>&mdash;</td></tr>"
                )
            else:
                stat = entry.stat()
                rows.append(
                    f'<tr><td><a href="{self._link(name)}">&#128196; {name}</a></td>'
                    f"<td>{human_size(stat.st_size)}</td>"
                    f'<td>{datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M}</td></tr>'
                )
            shown += 1
        if self.server.read_only:
            upload = ""
        else:
            action = "/upload" + (
                "?token=" + urllib.parse.quote(self.server.token) if self.server.token else ""
            )
            upload = (
                f'<form class="upload" method="post" action="{action}" '
                'enctype="multipart/form-data">'
                '<input type="file" name="file" multiple required> '
                "<button>Upload</button>"
                f'<p class="hint">Max {self.server.max_bytes // (1024 * 1024)} MB per request '
                "&middot; duplicate names get an auto suffix</p></form>"
            )
        return PAGE.format(
            path=folder.name or "/",
            upload=upload,
            rows="\n".join(rows),
            version=__version__,
        )

    def _send_file(self, path: Path) -> None:
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        preview = ctype.startswith(("image/", "text/", "application/pdf"))
        disposition = "inline" if preview else "attachment"
        filename = urllib.parse.quote(path.name)
        try:
            size = path.stat().st_size
        except OSError:
            self.send_error(404, "Not found")
            return
        start, end, status = 0, size - 1, 200
        range_header = (self.headers.get("Range") or "").strip()
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header) if range_header else None
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:  # suffix form: last N bytes
                start = max(0, size - int(match.group(2)))
            if start >= size or end < start:
                body = b"requested range not satisfiable\n"
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            end = min(end, size - 1)
            status = 206
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(remaining))
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header(
                    "Content-Disposition", f"{disposition}; filename*=UTF-8''{filename}"
                )
                self.end_headers()
                while remaining > 0:
                    chunk = handle.read(min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # ---- POST ---------------------------------------------------------
    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/upload":
            self.send_error(404, "Unknown endpoint")
            return
        if not self._authorized():
            self.send_error(401, "Token required")
            return
        if self.server.read_only:
            self.send_error(403, "Forbidden", "server runs in read-only mode")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.send_error(400, "Empty request")
            return
        if length > self.server.max_bytes:
            self._drain(length)
            self.send_error(413, "Payload too large")
            return
        raw = self.rfile.read(length)
        saved = self._save_upload(raw)
        if saved is None:
            self.send_error(400, "Malformed multipart body")
            return
        if "application/json" in (self.headers.get("Accept") or ""):
            body = json.dumps({"saved": saved}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(303)
            self.send_header("Location", self._link("", True))  # back to the listing
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _save_upload(self, raw: bytes):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype or "boundary=" not in ctype:
            return None
        parser = email.parser.BytesParser(policy=email.policy.default)
        try:
            message = parser.parsebytes(
                b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + raw
            )
        except Exception:
            return None
        saved = []
        for part in message.iter_parts():
            filename = part.get_filename()
            if not filename:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            target = self._unique_path(self._safe_name(filename))
            target.write_bytes(payload)
            saved.append({"name": target.name, "size": len(payload)})
        return saved

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = os.path.basename(filename.replace("\\", "/"))
        name = UNSAFE_NAME.sub("_", name).strip(". ")
        return name or "upload.bin"

    def _unique_path(self, name: str) -> Path:
        target = self.server.root / name
        if not target.exists():
            return target
        stem, suffix = Path(name).stem, Path(name).suffix
        for i in range(1, 1000):
            candidate = self.server.root / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                return candidate
        return self.server.root / f"{stem} ({int(time.time())}){suffix}"


def serve(args: argparse.Namespace) -> None:
    root = Path(args.dir).resolve()
    if not root.is_dir():
        sys.exit(f"error: {root} is not a directory")
    server = ShareServer(
        (args.bind, args.port),
        ShareHandler,
        root=root,
        read_only=args.read_only,
        token=args.token,
        max_mb=args.max_mb,
    )
    ip = "127.0.0.1" if args.bind in ("127.0.0.1", "localhost") else lan_ip()
    port = server.server_address[1]
    print(f"\n  lan-share v{__version__} -- sharing {root}")
    print(f"  local   http://127.0.0.1:{port}/")
    print(f"  network http://{ip}:{port}/")
    if args.token:
        print(f"  token   {args.token}  (append ?token=... to every URL)")
    if args.read_only:
        print("  mode    read-only")
    print("  Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="lan-share", description="Share a folder over your LAN with one command."
    )
    parser.add_argument("--dir", default=".", help="folder to share (default: current)")
    parser.add_argument("--bind", default="0.0.0.0", help="interface to bind (default: all)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    parser.add_argument("--read-only", action="store_true", help="disable uploads")
    parser.add_argument("--token", help="require ?token=<value> on every request")
    parser.add_argument(
        "--max-mb", type=int, default=512, help="max upload size in MB (default: 512)"
    )
    parser.add_argument("--version", action="version", version=f"lan-share {__version__}")
    serve(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
