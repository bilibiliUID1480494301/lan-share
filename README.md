# lan-share

[![CI](https://github.com/bilibiliUID1480494301/lan-share/actions/workflows/ci.yml/badge.svg)](https://github.com/bilibiliUID1480494301/lan-share/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

> One command, zero dependencies: share a folder over your LAN.
> 一条命令、零依赖，把文件夹共享给整个局域网。

`lan-share` is a single-file HTTP file server for local networks. Phone, tablet or
another PC on the same Wi-Fi can browse, download **and upload** files through a
browser — no install, no account, no cloud.

## Quick start

```bash
python lan_share.py --dir ./photos --port 8000
```

```
  lan-share v0.1.0 -- sharing E:\dev\photos
  local   http://127.0.0.1:8000/
  network http://192.168.1.23:8000/
  Ctrl+C to stop
```

Open the *network* URL on any device in the same LAN. That's it.

## Options

| Option | Default | Description |
|---|---|---|
| `--dir` | `.` | folder to share |
| `--bind` | `0.0.0.0` | interface to bind |
| `--port` | `8000` | TCP port |
| `--read-only` | off | disable uploads |
| `--token` | off | require `?token=<value>` on every request |
| `--max-mb` | `512` | max upload size per request (MB) |

## Features

- **Browse & download** — clean, mobile-friendly listing with sizes and mtimes.
- **Upload** — drag files into the page; duplicate names get an auto ` (1)` suffix.
- **Read-only mode** — `--read-only` turns uploads off entirely.
- **Token gate** — `--token mysecret` requires `?token=mysecret` on every URL.
- **Path-traversal protection** — requests are resolved and verified to stay
  inside the shared root; escaping paths get a `403`.
- **Upload hardening** — filenames are sanitized, request size is capped (`413`),
  malformed multipart bodies are rejected.
- **JSON API** — send `Accept: application/json` to `POST /upload` and get a
  machine-readable reply, handy for scripting:

  ```bash
  curl -H "Accept: application/json" -F "file=@report.pdf" http://192.168.1.23:8000/upload
  ```

## Security notes

This tool speaks plain HTTP and has no per-user auth. It is designed for
**trusted home / lab networks**. For semi-public networks use `--token` and
`--read-only`, and stop the server when you are done.

## Testing

```bash
python -m unittest discover -s tests -t . -v
```

CI runs the suite on Python 3.9–3.13 (see `.github/workflows/ci.yml`).

## Roadmap

See the [open issues](../../issues) — HTTP Range/resume, folder-zip download,
session cookies instead of query-string tokens.

## License

[MIT](LICENSE)

---

> **AI-assisted development statement / AI 辅助开发声明**: this project was written
> with the help of an AI coding agent and is published as a real, working tool —
> every feature is covered by the unit tests in [`tests/`](tests/).
