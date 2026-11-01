# Troubleshooting

Start with:

```bat
dl.cmd doctor
```

It prints engine versions, ffmpeg/aria2, Node, the detected proxy, a proxy HTTP
probe, and free disk. Most failures are visible there.

## First three checks

1. **Does the URL open in a browser through the same proxy?** If not, the tool
   cannot fix it.
2. **Is the tool in project-root context?** `dl.cmd` must run from
   `F:\work\download` (or be called by absolute path). It sets `PYTHONPATH`,
   ffmpeg, and aria2 for the child process.
3. **Is the content actually downloadable?** DRM, paywalls, private accounts, and
   expired signed URLs fail by design.

## Proxy problems

| Check | Command |
|---|---|
| Proxy port is listening | `Test-NetConnection 127.0.0.1 -Port 7890` |
| Proxy reaches HTTP | `dl.cmd doctor` (`http OK (204)`) |
| Bypass proxy | `dl.cmd doctor --no-proxy` |
| Force another proxy | `dl.cmd doctor --proxy http://127.0.0.1:7891` |

The configured proxy is `http://127.0.0.1:7890` in `config.json`. Environment
variables (`HTTPS_PROXY`, `HTTP_PROXY`) override the config; `--proxy` overrides
both.

Some sites block datacenter proxy exits even when YouTube works. Try a different
proxy node, or `--no-proxy` for that site if a direct route exists.

## Cookies and logins

Symptoms: 401, 403, "login required", "This content is not available", empty
gallery, only preview images.

```bat
dl.cmd images "https://www.pixiv.net/artworks/..." --cookies --browser edge
dl.cmd video "https://www.bilibili.com/video/BV..." --cookies --browser edge
```

- Use `--browser chrome`, `firefox`, or `brave` if Edge is not the logged-in one.
- Chromium keeps its cookie database locked while running. If cookie extraction
  fails, close the browser and retry.
- A cookie file exported in Netscape format works too:
  `--cookie-file C:\path\cookies.txt`.
- Cookies are credentials. Do not paste them into chat, commit them, or share
  `state\`.

## yt-dlp errors

### "Unsupported URL"
The site may be supported only through a generic embed. Try:

```bat
dl.cmd article "<url>"
dl.cmd file "<url>"
dl.cmd update
```

If it is a known site, check `yt-dlp --list-extractors | findstr /i <site>`.
A missing extractor means the site is not supported yet.

### "Requested format is not available"
- Try `--quality best` first.
- Log in with cookies: many sites hide high-bitrate formats from anonymous
  sessions.
- `dl.cmd update` to get newer format mappings.

### "n challenge" / "Some formats may be missing"
The Node.js runtime and remote EJS component are already enabled. If it still
appears:
- `dl.cmd update`
- Ensure `node --version` works.
- Delete `state\cache\yt-dlp\challenge-solver` and retry (it re-downloads).

### HTTP 403 / 429
- 403: cookies, region, or a required `Referer`. yt-dlp sets most referers; for a
  stubborn site, download the page URL rather than a direct media URL.
- 429: wait several minutes, avoid parallel downloads from the same host, and use
  `--limit-rate 2M`.

### Merge or audio conversion fails
ffmpeg is required for separate video/audio streams and for `-x`.
`dl.cmd doctor` must show a version. If it does not:

```bat
tools\ffmpeg\bin\ffmpeg.exe -version
```

Re-extract a fresh ffmpeg build into `tools\ffmpeg\bin` if the binary is missing
or corrupt.

## gallery-dl errors

### "No results" / empty output
- The URL may be a single image; force `dl.cmd file "<image-url>"` instead.
- Login or cookies may be required.
- Some extractors need a specific URL shape (artwork page, not the CDN link).

### "429 Too Many Requests"
gallery-dl retries automatically, but aggressive ranges still trigger blocks.
Download one page/range at a time and wait. `--limit-rate` is not supported by
gallery-dl, so use its `--sleep-request` option through a config file if needed.

### Ugoira / animated images
Pixiv ugoira needs ffmpeg to assemble frames. Confirm `dl.cmd doctor` sees
ffmpeg; then retry with `--force`.

## Article extraction

### "no readable article body found"
- The page may be a JS-only app or a paywall.
- Save raw HTML for inspection: `dl.cmd file "<url>" --name page.html`.
- Try the site's print view or AMP URL.
- PDFs are not articles; use file mode.

### Mojibake / wrong Chinese characters
The fetcher honors the HTTP charset, then `<meta charset>`, then UTF-8. A few
legacy GBK pages omit both. Save the raw page and convert explicitly with
`iconv`/Python if needed.

## File downloads

### "incomplete download"
The server closed early. Rerun the same command; the `.part` file resumes. If the
server does not support ranges, the downloader restarts from zero.

### File locked / WinError 32
A player, editor, or antivirus has the file open. Close it and rerun. If the
`.part` file is locked, wait for the scanner and retry.

### HTML saved instead of the real file
The link was a landing/confirmation page. Use the direct-download URL. Google
Drive large files and some CDNs need a browser cookie or a confirm token.

### Filename looks truncated
Windows and exFAT limit names; video titles are trimmed to 180 bytes and
sanitized. Use `--name` for a short, stable name.

## Torrents

### Magnet never starts
- The tracker/DHT route may be blocked. aria2 needs direct UDP/TCP; an HTTP proxy
  only covers tracker HTTP requests.
- Try a `.torrent` file instead of a magnet.
- `--bt-stop-timeout=300` is intentional: the tool stops after 5 minutes without
  progress rather than hanging forever.

## Updating and repairing

```bat
dl.cmd update
dl.cmd doctor
```

`update` installs the latest yt-dlp, gallery-dl, and trafilatura into
`tools\pylibs`. If pip fails behind the proxy, run it with `--proxy` explicitly:

```bat
dl.cmd update --proxy http://127.0.0.1:7890
```

To rebuild the Python environment from scratch, delete `tools\pylibs` and run
`dl.cmd update`. To rebuild ffmpeg, replace `tools\ffmpeg\bin` with a fresh
static build. To rebuild aria2, replace `tools\aria2\aria2c.exe`.

## Where to look

| Path | Contents |
|---|---|
| `state\history.jsonl` | every attempt: URL, mode, files, bytes, error |
| `state\ytdlp-archive.txt` | video IDs already downloaded |
| `state\gallery-archive.sqlite3` | gallery URLs already downloaded |
| `state\cache\` | yt-dlp EJS solver cache |
| `downloads\YYYY-MM-DD\` | default output |

Do not delete `.part` or `.aria2` files unless you intend to restart.