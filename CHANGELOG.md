# Changelog

All notable changes to this project are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Planned
- HTTP Range requests / resume downloads

## [0.1.0] - 2026-10-03
### Added
- Directory listing with sizes and mtimes
- File download with correct Content-Type / Content-Disposition
- Multipart upload endpoint (`POST /upload`) with JSON or redirect responses
- `--dir`, `--bind`, `--port`, `--read-only`, `--token`, `--max-mb` options
- Path-traversal protection and upload filename sanitization
- Auto-suffix for duplicate upload names (`doc (1).txt`)
- Unit tests and CI on Python 3.9-3.13
