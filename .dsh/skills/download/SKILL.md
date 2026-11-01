---
name: download
description: Download video, audio, image galleries, direct files, torrents, or clean article text from a URL on this Windows machine. Use when the user asks to download/save/grab/rip a link, gives a playlist or gallery, needs a file fetched reliably, or a browser download failed. Routes to yt-dlp, gallery-dl, aria2, or trafilatura with proxy, resume, and archive support.
whenToUse: The user supplies a URL, magnet link, or .torrent and wants the content saved locally; or asks to extract an article as Markdown; or needs a batch of links downloaded; or a normal browser download is blocked, partial, or too slow.
---

# Download

One command handles video, audio, image galleries, direct files, articles, and torrents. It detects the content type, picks the best engine, reuses the configured proxy, resumes partial files, and records history.

Run everything from the project root `F:\work\download` (the session working directory).

## Quick start

```bat
dl.cmd doctor
dl.cmd "https://www.youtube.com/watch?v=..."
dl.cmd "https://example.com/article"
```

`dl.cmd` sets `PYTHONPATH`, ffmpeg, and aria2 automatically. Do not call the Python script directly unless debugging.

If a link has no scheme, add `https://`.

## Routing

| Content | Command | Engine |
|---|---|---|
| Video, playlist, live replay | `dl.cmd video <url>` | yt-dlp |
| Audio only | `dl.cmd audio <url>` | yt-dlp + ffmpeg |
| Image post / gallery / album | `dl.cmd images <url>` | gallery-dl |
| Direct file (zip, pdf, exe, iso...) | `dl.cmd file <url>` | Python (aria2 for HTTP) |
| Article / blog / docs page | `dl.cmd article <url>` | trafilatura -> Markdown |
| Magnet or .torrent | `dl.cmd torrent <magnet-or-url>` | aria2 |
| Let the router decide | `dl.cmd <url>` | auto |

Forcing a mode is the escape hatch when auto-detection guesses wrong. `--mode` also works on `get`.

## Useful options

| Option | Effect |
|---|---|
| `--quality 1080` | cap video height (`2160/1440/1080/720/480/best`) |
| `--playlist` | download the whole playlist (default: single item) |
| `--cookies --browser edge` | use browser login (Bilibili 1080p, X, Pixiv, Instagram...) |
| `--cookie-file cookies.txt` | use an exported Netscape cookie file |
| `--audio-format m4a` | audio container (`mp3/m4a/opus/flac/wav`) |
| `--subs` | download and embed subtitles |
| `--out D:\Media` | exact output directory |
| `--name "lesson-01"` | rename a single output |
| `--flat` | skip the `YYYY-MM-DD` folder |
| `--force` | ignore the archive and overwrite |
| `--dry-run` | show engine and destination only |
| `--json` | machine-readable summary |
| `--proxy http://127.0.0.1:7890` | override proxy |
| `--no-proxy` | direct connection |
| `--limit-rate 2M` | throttle |

## Output contract

- Default destination: `downloads\YYYY-MM-DD\`; videos add an uploader subfolder.
- On success the CLI prints `[saved] <absolute path>` and `[ok] <count> file(s), <size>, <time>`.
- Report the absolute path, size, and title to the user. Do not paste engine logs.
- `state\history.jsonl` records every attempt; `state\ytdlp-archive.txt` and `state\gallery-archive.sqlite3` prevent duplicates.
- A rerun of the same command resumes a `.part` file instead of restarting.

## Workflow

1. Run `dl.cmd doctor` once per session if anything looks broken (proxy, ffmpeg, versions).
2. Classify the request. If the user names a platform or the URL is obvious, use the explicit subcommand; otherwise use `dl.cmd <url>`.
3. Estimate size/duration. For a playlist, long video, or gallery, start it as a background job, then poll and report progress. For small single files, run inline.
4. On success, verify the file exists and is non-zero; give the path and a one-line summary.
5. On failure, read the last error line, apply the matching playbook below, and retry once before asking the user.

## Failure playbook

| Symptom | Action |
|---|---|
| 401/403, "login required", empty gallery | Retry with `--cookies --browser edge` (or `--cookie-file`). Ask before using cookies on a new site. |
| 429 / "Too Many Requests" | Wait, lower `--limit-rate`, retry; avoid parallel runs against one host. |
| "Requested format is not available" | `--quality best`, then `dl.cmd update`; some formats need cookies. |
| YouTube "n challenge" / missing formats | `dl.cmd update`; node is already wired with `--remote-components ejs:github`. |
| "Unsupported URL" | Try `--mode article` for a page, `--mode file` for a raw asset, then `dl.cmd update`. |
| `ffmpeg` / merge / audio conversion error | `dl.cmd doctor`; reinstall ffmpeg under `tools\ffmpeg\bin`. |
| Proxy / timeout / TLS error | `dl.cmd doctor`; confirm the proxy port, or retry `--no-proxy`. |
| File locked (WinError 32) | Close the player/editor using it, rerun. |
| Partial `.part` file | Rerun the same command; use `--force` only to restart from zero. |
| Disk full | Check `dl.cmd doctor`; choose `--out` on another drive. |

Do not delete `.part` or `.aria2` files unless the user asks: they are resume state.

## Guardrails

- Download only public content or content the user is authorized to access. Do not bypass DRM, paywalls, or access controls.
- Cookies are credentials. Use them only after the user agrees, never print their contents, and never commit `state\` or cookie files.
- Respect site terms and rate limits; prefer one item at a time over aggressive parallelism.
- Keep the original page URL in article frontmatter and history for provenance.

## References

- `references/sites.md` — per-platform notes and the exact flags that matter.
- `references/troubleshooting.md` — deeper diagnosis and recovery commands.