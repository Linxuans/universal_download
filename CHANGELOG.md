# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

## [2.0.2] - 2026-11-02

### Fixed
- Bumped the Scout report cache schema. The v2.0.1 Chinese-skill fixes were
  masked by 24-hour-old cached reports that still contained zero skills; the
  new schema forces a fresh search for existing goals.

## [2.0.1] - 2026-11-02

### Fixed
- Chinese-only goals such as 「我想自己开发一个游戏」 and 「写小说」 now map to
  English search terms (`game`, `novel`, `writing`, `develop`); previously the
  query core was empty and only plugins matched.
- Code-search skills inside large monorepos are no longer rejected by the
  300 MB repo-size guard when the exact `SKILL.md` path is known.
- English term matching uses word boundaries, so `book` no longer matches
  `workbook` or `notebook`.
- MCP servers get a small ranking boost when the goal explicitly asks for MCP.
- Code-search rate-limit failures are reported instead of silently yielding zero
  skill results.

## [2.0.0] - 2026-11-02

### Added
- Scout v2.0: describes a project goal in natural language and recommends
  high-star GitHub Agent Skills, DSH plugins/MCP servers, and local skills.
- GitHub repository search plus `filename:SKILL.md` code search, with SKILL.md
  frontmatter/body reading, license, stars, freshness, and risk checks.
- Public DSH plugin registry (8,100+ entries) cached for 24 hours, npm fallback,
  and MCP detection.
- Intent-aware scoring: goal actions/platforms are required before a popular but
  irrelevant repository can rank; local skills are surfaced first.
- Markdown and JSON reports, 24h cache, `scout.cmd` CLI, `scout` project skill,
  and a new "发现" view in the desktop UI.
- Offline unit tests for query parsing, intent matching, frontmatter, and report
  rendering.

### Notes
- Scout is read-only in v2.0. It never installs, enables, or executes a
  recommended skill/plugin.
- GitHub token is read from `GITHUB_TOKEN`, `.env`, or Git Credential Manager;
  it is never written to disk or printed.

## [1.1.0] - 2026-11-01

### Added
- FetchDesk desktop UI: sidebar navigation, URL hero, mode chips, quality and
  advanced options, live job progress, log tail, history, settings, theme
  toggle, and a custom app icon.
- `--progress-file` on every download command, writing atomic JSON progress
  records for the UI (direct files, yt-dlp, gallery-dl, articles, torrents).
- `scripts/gui.py`: local HTTP API plus an Edge `--app` window with a dedicated
  profile, so the UI has no address bar and closes back to the desktop.
- `scripts/create_shortcut.ps1` and `gui.cmd`; a desktop shortcut named
  「下载工作台」 is generated with the bundled icon.
- `scripts/make_icon.py` for regenerating the PNG/ICO artwork.

### Changed
- `dl.py` now reports progress independently of stdout, keeping the CLI output
  readable while the GUI gets structured updates.

### Notes
- The GUI is deliberately not a pywebview/pythonnet app: those need process
  handle access that the DSH sandbox denies. Edge app mode is the stable
  desktop target here.
- API, static assets, job execution, progress, and history were verified
  headlessly. The Edge window itself must be launched in a normal desktop
  session; the sandbox blocks Edge's process broker.

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
