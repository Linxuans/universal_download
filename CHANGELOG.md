# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

## [1.0.0] - 2026-11-01

### Added
- `dl.cmd`, a single Windows entry point that routes a URL to the right engine.
- Video and audio downloads through yt-dlp, including playlists, subtitles,
  quality caps, browser cookies, metadata embedding, and the YouTube EJS
  challenge solver via Node.js.
- Image and gallery downloads through gallery-dl, with archive-based dedupe.
- Resumable direct-file downloads with `Content-Disposition` filenames, `.part`
  recovery, progress reporting, and an aria2 multi-connection path for HTTP.
- Clean article extraction through trafilatura, with title/author/date/url
  frontmatter and UTF-8/GBK-aware decoding.
- Magnet and `.torrent` downloads through aria2 with seeding disabled.
- Proxy auto-detection (CLI, environment, `config.json`, Windows registry) and
  a `doctor` command covering engines, proxy reachability, and disk space.
- Per-day output folders, safe Windows filenames, download history, and
  yt-dlp/gallery-dl archives.
- Project-local DSH skill at `.dsh/skills/download/` with site notes and a
  troubleshooting reference.
- `setup.ps1` / `scripts/bootstrap.py` for reproducible installs on a new
  machine, plus `requirements.txt`.
- Verified end-to-end against YouTube video/audio, Wikipedia (zh/en), GitHub raw
  files (including resume), Wikimedia images, and an HTTP direct link.

### Notes
- aria2's WinTLS backend cannot initialize in the restricted DSH token, so HTTPS
  direct files automatically use the resumable Python downloader. HTTP and
  BitTorrent still use aria2.
- DRM, paywalls, and proprietary cloud drives (Baidu Pan, Quark) are out of
  scope by design.
