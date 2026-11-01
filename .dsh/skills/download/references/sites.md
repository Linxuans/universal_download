# Site notes

These are the platform-specific details that change the right command. The
general rule still applies: try `dl.cmd <url>`, then force a mode only when the
router guesses wrong.

## Video platforms

### YouTube
- Works without cookies for public videos. `dl.cmd video <url>`.
- The bundle wires Node.js as the JavaScript runtime and enables
  `--remote-components ejs:github`, so the `n` challenge solver is available.
- 1080p/4K, age-restricted, members-only, or region-locked videos often need
  `--cookies --browser edge`.
- A URL containing `list=` downloads one video by default. Add `--playlist` for
  the whole playlist.
- Subtitles: `--subs` writes Chinese/English tracks and embeds them.
- Live streams: yt-dlp records from the current point; stop with Ctrl+C and the
  partial `.part` file is resumable while the stream is still live.

### Bilibili
- Public 360p/480p usually works without login. 1080P, 1080P+, 4K, and some
  bangumi need a logged-in cookie: `--cookies --browser edge`.
- Multi-part videos: the URL's `?p=N` selects one part. Use `--playlist` to get
  every part.
- If a video is region-locked, the proxy must exit in the allowed region; a
  cookie alone is not enough.

### TikTok / Douyin / Kuaishou
- Cookies and a matching region usually matter. `--cookies --browser edge`.
- Watermark-free output depends on the extractor and the current site behavior;
  do not promise it.
- Short links (`v.douyin.com/...`) are followed automatically.

### Twitch / live
- Past broadcasts and clips work like normal videos.
- Live streams are indefinite: run in the background job system, not inline.

### DRM platforms
- iQIYI, Youku, Tencent Video, Netflix, Disney+, and similar services use DRM.
  yt-dlp will fail or return only trailers. Do not attempt to bypass DRM.

## Image platforms

### Pixiv
- Login is required for many works and for original-size files:
  `dl.cmd images <artwork-url> --cookies --browser edge`.
- gallery-dl handles multi-page works, novels, and ugoira. Ugoira conversion
  needs ffmpeg, which is already on `PATH` for `dl.cmd`.

### X / Twitter
- `dl.cmd images <post-url>` for images; `dl.cmd video <post-url>` for video.
- Protected accounts need cookies. A post with several images becomes a folder.
- gallery-dl's `twitter` extractor is usually better for timelines and media
  tabs; pass the profile URL and use `--cookies`.

### Instagram / Facebook
- Most content now requires a logged-in session. Use `--cookies`.
- Expect rate limits and periodic checkpoint pages. Download one profile or post
  at a time; lower concurrency does not fix a checkpoint, only a browser login.

### Reddit
- `dl.cmd images <post-or-subreddit-url>` uses gallery-dl.
- Reddit may return a login wall or rate limit. Cookies help; NSFW subreddits
  require account preferences that cookies carry.

### Weibo / Lofter / Huaban
- gallery-dl has extractors for these. Login cookies are often needed for full
  albums and original images.
- Weibo's visitor cookie expires quickly; re-run with fresh browser cookies.

### ArtStation / DeviantArt / Flickr / Behance
- Public pages generally work. Flickr and DeviantArt may need cookies for
  mature or private content.
- ArtStation may serve resized previews without login; the original asset needs
  a session.

## Articles and documents

### Blogs, news, docs
- `dl.cmd article <url>` returns clean Markdown with title/author/date
  frontmatter. It strips navigation, ads, and scripts.
- Paywalled pages return only the public preview. The tool does not bypass
  paywalls; use the user's own subscription in a browser.
- If extraction returns too little text, use `--mode file` to save the raw HTML
  and inspect it, or open the print view in a browser.

### PDFs and ebooks
- A URL ending in `.pdf`, `.epub`, `.mobi`, or `.djvu` goes to file mode.
- Some PDF links are behind a redirector; the final `Content-Disposition` name
  is used when available.
- Scanned PDFs need OCR; this tool does not OCR.

### Google Drive, Dropbox, OneDrive
- Public "anyone with the link" files may download as HTML confirmation pages.
  Prefer the direct-download URL (`drive.google.com/uc?export=download&id=...`).
- Large Google Drive files trigger a virus-scan confirmation page; file mode
  will save HTML instead of the file. Use the browser or `gdown` for those.

### Baidu Pan / Quark / Aliyun
- These require proprietary clients and login flows; they are not supported by
  yt-dlp or gallery-dl. Use the official client or a user-provided direct link.

## Direct files and archives

- `dl.cmd file <url>` uses multi-connection aria2 for HTTP and the resumable
  Python downloader for HTTPS (aria2's Windows TLS backend is unreliable in
  restricted tokens).
- The filename comes from `Content-Disposition`, then the URL path. Override with
  `--name`.
- A rerun resumes `.part`; `--force` restarts from zero.
- Verify large archives yourself (SHA-256 is printed by many release pages).
  The downloader records size and source URL in `state\history.jsonl`.

## Torrents

- `dl.cmd torrent <magnet-or-.torrent>` uses aria2 with seeding disabled.
- A `.torrent` URL is downloaded first, then opened locally.
- The tool stops after the download completes; it is not a seedbox.
- Only use torrents you have the right to download.