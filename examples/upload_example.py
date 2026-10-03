#!/usr/bin/env python3
"""Upload a file to a running lan-share server (JSON API).

Usage:
    python upload_example.py http://192.168.1.23:8000 report.pdf
    python upload_example.py http://192.168.1.23:8000 report.pdf --token s3cret
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path


def upload(url: str, path: str, token: str | None = None) -> dict:
    """POST one file as multipart/form-data and return the JSON reply."""
    file_path = Path(path)
    boundary = "----lanshareexample7d1a2c"
    ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    body = bytearray()
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    target = url.rstrip("/") + "/upload"
    if token:
        target += "?token=" + urllib.parse.quote(token)
    req = urllib.request.Request(
        target,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a file to a lan-share server.")
    parser.add_argument("url", help="server base URL, e.g. http://192.168.1.23:8000")
    parser.add_argument("file", help="file to upload")
    parser.add_argument("--token", help="token if the server was started with --token")
    args = parser.parse_args()
    result = upload(args.url, args.file, args.token)
    for item in result.get("saved", []):
        print(f"saved: {item['name']} ({item['size']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
