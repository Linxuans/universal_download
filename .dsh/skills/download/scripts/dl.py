#!/usr/bin/env python3
"""One-command downloader for Windows.

Routes a URL to the right engine:
  video / audio  -> yt-dlp (1000+ sites, HLS/DASH, playlists, subtitles)
  images         -> gallery-dl (pixiv, danbooru, twitter, reddit, ...)
  direct file    -> aria2c (multi-connection) with a Python fallback
  article        -> trafilatura (clean Markdown, no ads/nav)
  torrent/magnet -> aria2c

Only the engines in ``tools/pylibs`` are optional extras; the fallback file
downloader and all orchestration use the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[4]
PYLIBS = ROOT / "tools" / "pylibs"
FFMPEG_DIR = ROOT / "tools" / "ffmpeg" / "bin"
ARIA2_EXE = ROOT / "tools" / "aria2" / "aria2c.exe"
STATE = ROOT / "state"
CONFIG_PATH = ROOT / "config.json"
GALLERY_CONFIG = ROOT / "config" / "gallery-dl.json"

if str(PYLIBS) not in sys.path:
    sys.path.insert(0, str(PYLIBS))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG = {
    "proxy": "http://127.0.0.1:7890",
    "autoProxy": True,
    "downloadRoot": "downloads",
    "dateSubfolders": True,
    "browser": "edge",
    "retries": 10,
    "fragments": 4,
    "videoTemplate": "%(uploader,channel,creator|Unknown)s/%(title).150B [%(id)s].%(ext)s",
    "embedMetadata": True,
    "writeSubtitles": False,
}

VIDEO_HOSTS = {
    "youtube.com", "youtu.be", "youtube-nocookie.com", "bilibili.com", "b23.tv",
    "vimeo.com", "dailymotion.com", "twitch.tv", "tiktok.com", "douyin.com",
    "iesdouyin.com", "kuaishou.com", "ixigua.com", "acfun.cn", "nicovideo.jp",
    "iqiyi.com", "youku.com", "mgtv.com", "v.qq.com", "sohu.com", "le.com",
    "facebook.com", "fb.watch",
    "soundcloud.com", "bandcamp.com", "ted.com", "rumble.com",
    "odysee.com", "bitchute.com", "streamable.com", "vk.com", "ok.ru",
    "coursera.org", "udemy.com", "skillshare.com", "archive.org",
}

GALLERY_HOSTS = {
    "pixiv.net", "pximg.net", "danbooru.donmai.us", "e-hentai.org",
    "exhentai.org", "artstation.com", "deviantart.com", "flickr.com",
    "imgur.com", "pinterest.com", "pinterest.co.uk", "tumblr.com",
    "bsky.app", "weibo.com", "weibo.cn", "lofter.com", "huaban.com",
    "behance.net", "unsplash.com", "pexels.com", "500px.com",
    "twitter.com", "x.com", "reddit.com", "instagram.com",
}

DIRECT_EXTS = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".zst", ".iso",
    ".exe", ".msi", ".msix", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".appimage",
    ".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".csv", ".tsv", ".json", ".xml", ".txt", ".md",
    ".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".wma",
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts", ".m4v", ".wmv",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".svg", ".avif", ".heic", ".psd", ".ai", ".torrent", ".bin", ".dat",
}

MEDIA_EXTS = {
    ".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac",
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts", ".m4v", ".wmv",
    ".m3u8", ".mpd",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".avif", ".heic"}


class DlError(RuntimeError):
    pass


@dataclass
class Result:
    url: str
    mode: str
    ok: bool
    directory: Path
    files: list[Path] = field(default_factory=list)
    bytes: int = 0
    seconds: float = 0.0
    title: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "mode": self.mode,
            "ok": self.ok,
            "directory": str(self.directory),
            "files": [str(p) for p in self.files],
            "bytes": self.bytes,
            "seconds": round(self.seconds, 1),
            "title": self.title,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def eprint(*a, **kw):
    print(*a, file=sys.stderr, **kw)


def human(n: int | float | None) -> str:
    if not n:
        return "0 B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def safe_name(value: str, maxlen: int = 140) -> str:
    value = unicodedata.normalize("NFC", str(value or "")).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = "download"
    stem = value.split(".")[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
                "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}:
        value = "_" + value
    return value[:maxlen].rstrip(" .")


def slug(value: str, maxlen: int = 80) -> str:
    value = unicodedata.normalize("NFC", value or "").strip()
    value = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_]+", "-", value).strip("-")
    return (value or "article")[:maxlen].strip("-")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
        except Exception as exc:
            eprint(f"[warn] cannot read {CONFIG_PATH.name}: {exc}")
    return cfg


def proxy_from_registry() -> str | None:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not enable or not server:
            return None
        if "=" in server:
            parts = dict(p.split("=", 1) for p in server.split(";") if "=" in p)
            server = parts.get("https") or parts.get("http") or ""
        if server and "://" not in server:
            server = "http://" + server
        return server or None
    except Exception:
        return None


def resolve_proxy(cfg: dict, disabled: bool, explicit: str | None) -> str | None:
    if disabled:
        return None
    if explicit:
        return explicit if "://" in explicit else "http://" + explicit
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(name)
        if val:
            return val if "://" in val else "http://" + val
    if cfg.get("autoProxy", True):
        configured = cfg.get("proxy")
        if configured and tcp_ok(configured):
            return configured if "://" in configured else "http://" + configured
        reg = proxy_from_registry()
        if reg and tcp_ok(reg):
            return reg
    return None


def proxy_hostport(proxy: str | None) -> tuple[str, int] | None:
    if not proxy:
        return None
    p = urllib.parse.urlparse(proxy if "://" in proxy else "http://" + proxy)
    if not p.hostname:
        return None
    return p.hostname, p.port or (443 if p.scheme == "https" else 80)


def tcp_ok(proxy: str, timeout: float = 1.5) -> bool:
    hp = proxy_hostport(proxy)
    if not hp:
        return False
    try:
        with socket.create_connection(hp, timeout=timeout):
            return True
    except OSError:
        return False


def proxy_handler(proxy: str | None):
    if not proxy:
        return urllib.request.ProxyHandler({})
    return urllib.request.ProxyHandler({"http": proxy, "https": proxy})


def build_opener(proxy: str | None, insecure: bool = False):
    handlers = [proxy_handler(proxy)]
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def subprocess_env(proxy: str | None) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PYLIBS) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(FFMPEG_DIR) + os.pathsep + str(ARIA2_EXE.parent) + os.pathsep + env.get("PATH", "")
    if proxy:
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = env["ALL_PROXY"] = proxy
        env["http_proxy"] = env["https_proxy"] = env["all_proxy"] = proxy
        env.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
    else:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
    return env


def certifi_bundle() -> Path | None:
    candidate = PYLIBS / "certifi" / "cacert.pem"
    return candidate if candidate.exists() else None


def parse_suffix(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    return Path(path).suffix


def host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def host_in(host: str, hosts: Iterable[str]) -> bool:
    return any(host == h or host.endswith("." + h) for h in hosts)


def classify(url: str, proxy: str | None, cfg: dict) -> str:
    low = url.lower()
    if low.startswith("magnet:"):
        return "torrent"
    if url.startswith("file://"):
        return "file"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return "file"
    local = Path(url)
    if local.exists() and local.is_file():
        return "torrent" if local.suffix.lower() == ".torrent" else "file"
    host = host_of(url)
    suffix = parse_suffix(url)
    if suffix == ".torrent":
        return "torrent"
    if suffix in {".m3u8", ".mpd"}:
        return "video"
    if host_in(host, VIDEO_HOSTS) and suffix not in IMAGE_EXTS:
        return "video"
    if host_in(host, GALLERY_HOSTS):
        return "images"
    if suffix in DIRECT_EXTS:
        return "file"
    # Unknown host: inspect the response. A failed probe falls through to the
    # generic extractor, which handles many embed-only pages.
    try:
        info = probe(url, proxy, timeout=15)
        ctype = (info.get("content_type") or "").lower()
        if ctype.startswith("text/html") or ctype.startswith("application/xhtml"):
            return "article"
        if ctype.startswith("image/"):
            return "file"
        if ctype.startswith(("video/", "audio/")) or "mpegurl" in ctype or "dash+xml" in ctype:
            return "video"
        if ctype.startswith("application/") or ctype.startswith("binary/"):
            return "file"
    except Exception:
        pass
    return "video"

# --------------------------------------------------------------------------- #
# HTTP probing
# --------------------------------------------------------------------------- #

@dataclass
class Probe:
    url: str
    status: int
    content_type: str
    length: int | None
    filename: str | None
    final_url: str

    def get(self, key, default=None):
        return getattr(self, key, default)


def filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    msg = Message()
    msg["content-disposition"] = value
    name = msg.get_filename()
    if name:
        name = os.path.basename(name.replace("\\", "/"))
        return safe_name(name) or None
    return None


def filename_from_url(url: str) -> str | None:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    name = os.path.basename(path)
    if name and "." in name:
        return safe_name(name)
    return None


def probe(url: str, proxy: str | None, timeout: int = 25, insecure: bool = False) -> Probe:
    opener = build_opener(proxy, insecure)
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"}
    resp = None
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        resp = opener.open(req, timeout=timeout)
    except Exception:
        resp = None
    if resp is None:
        req = urllib.request.Request(url, headers={**headers, "Range": "bytes=0-0"})
        resp = opener.open(req, timeout=timeout)
    with resp:
        final = resp.geturl()
        status = getattr(resp, "status", 200)
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        length = None
        content_range = resp.headers.get("Content-Range", "")
        m = re.search(r"/(\d+)$", content_range)
        if m:
            length = int(m.group(1))
        elif resp.headers.get("Content-Length", "").isdigit():
            length = int(resp.headers["Content-Length"])
            if status == 206 and length <= 1:
                length = None
        name = filename_from_disposition(resp.headers.get("Content-Disposition")) or filename_from_url(final)
        return Probe(url, status, ctype, length, name, final)


# --------------------------------------------------------------------------- #
# engine runners
# --------------------------------------------------------------------------- #

def run_stream(cmd: list[str], env: dict, cwd: Path, mode: str, verbose: bool, timeout: int | None = None) -> tuple[int, list[str]]:
    if verbose:
        eprint("[cmd] " + " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
        )
    except FileNotFoundError as exc:
        raise DlError(f"engine not found: {cmd[0]} ({exc})") from exc
    lines: list[str] = []
    interesting = (
        "[download] Destination", "[Merger]", "[ExtractAudio]", "[Metadata]",
        "[FixupM3u8]", "[FixupM4a]", "[VideoConvertor]", "ERROR", "WARNING",
        "[info]", "Merging", "Deleting original file", "100%",
    )
    started = time.time()
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        lines.append(line)
        if verbose or any(k in line for k in interesting):
            print(f"  {line}", flush=True)
        if timeout and time.time() - started > timeout:
            proc.kill()
            raise DlError(f"{mode} timed out after {timeout}s")
    code = proc.wait()
    return code, lines


def collect_new_files(directory: Path, started: float) -> list[Path]:
    found: list[Path] = []
    skip = {".part", ".ytdl", ".tmp", ".temp"}
    if not directory.exists():
        return found
    for p in directory.rglob("*"):
        try:
            if not p.is_file() or p.suffix.lower() in skip:
                continue
            st = p.stat()
            if max(st.st_ctime, st.st_mtime) >= started - 5:
                found.append(p)
        except OSError:
            continue
    found.sort(key=lambda p: p.stat().st_mtime)
    return found


def parse_printed_paths(lines: list[str], directory: Path) -> list[Path]:
    paths: list[Path] = []
    for line in lines:
        line = line.strip().strip("'\"")
        if not line or line.startswith(("[", "ERROR", "WARNING")):
            continue
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = directory / line
        try:
            if candidate.exists() and candidate.is_file():
                paths.append(candidate)
        except OSError:
            continue
    return paths


def ytdlp_format(quality: str) -> str:
    if quality in ("best", ""):
        return "bv*+ba/b"
    if quality == "audio":
        return "ba/b"
    h = int(quality)
    return f"bv*[height<={h}]+ba/b[height<={h}]/b"


def download_video(url: str, out: Path, proxy: str | None, cfg: dict, opts: argparse.Namespace) -> Result:
    started_ts = time.time()
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--newline", "--no-color", "--no-mtime",
        "--windows-filenames", "--trim-filenames", "180",
        "--retries", str(cfg.get("retries", 10)),
        "--fragment-retries", str(cfg.get("retries", 10)),
        "--file-access-retries", "3",
        "--socket-timeout", "30",
        "--concurrent-fragments", str(cfg.get("fragments", 4)),
        "--continue", "--no-overwrites",
        "--cache-dir", str(STATE / "cache"),
        "--paths", str(out),
        "--print", "after_move:filepath",
    ]
    if proxy:
        cmd += ["--proxy", proxy]
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node", "--remote-components", "ejs:github"]
    archive = STATE / "ytdlp-archive.txt"
    if not opts.force:
        cmd += ["--download-archive", str(archive)]
    else:
        cmd += ["--force-overwrites"]
    if opts.playlist:
        cmd += ["--yes-playlist"]
    else:
        cmd += ["--no-playlist"]
    if opts.cookies:
        cmd += ["--cookies-from-browser", opts.browser]
    if opts.cookie_file:
        cmd += ["--cookies", opts.cookie_file]
    if opts.subs or cfg.get("writeSubtitles"):
        cmd += ["--write-subs", "--sub-langs", "zh-Hans,zh-Hant,zh,en", "--embed-subs"]
    if cfg.get("embedMetadata", True):
        cmd += ["--embed-metadata"]
    if opts.limit_rate:
        cmd += ["--limit-rate", opts.limit_rate]
    if opts.quality == "audio":
        cmd += ["-x", "--audio-format", opts.audio_format, "--audio-quality", "0"]
        cmd += ["-f", "ba/b"]
    else:
        cmd += ["-f", ytdlp_format(opts.quality)]
        if opts.quality not in ("best", ""):
            cmd += ["--merge-output-format", "mkv"]

    template = cfg.get("videoTemplate") or DEFAULT_CONFIG["videoTemplate"]
    if opts.name:
        template = safe_name(opts.name) + ".%(ext)s"
    cmd += ["-o", template, "--", url]

    print(f"[video] yt-dlp -> {out}")
    code, lines = run_stream(cmd, subprocess_env(proxy), ROOT, "yt-dlp", opts.verbose)
    files = parse_printed_paths(lines, out) or collect_new_files(out, started_ts)
    files = list(dict.fromkeys(p.resolve() for p in files if p.exists()))
    if code != 0:
        tail = "\n".join(lines[-12:])
        raise DlError(f"yt-dlp exited {code}\n{tail}")
    return Result(url, "audio" if opts.quality == "audio" else "video", True, out, files,
                  sum(p.stat().st_size for p in files), time.time() - started_ts)


def download_images(url: str, out: Path, proxy: str | None, cfg: dict, opts: argparse.Namespace) -> Result:
    started_ts = time.time()
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "-D", str(out),
        "--config-json", str(GALLERY_CONFIG),
        "--retries", str(cfg.get("retries", 4)),
        "--download-archive", str(STATE / "gallery-archive.sqlite3"),
        "--no-colors",
    ]
    if proxy:
        cmd += ["--proxy", proxy]
    if opts.cookies:
        cmd += ["--cookies-from-browser", opts.browser]
    if opts.cookie_file:
        cmd += ["--cookies", opts.cookie_file]
    if opts.force:
        cmd = [c for c in cmd if c not in ("--download-archive", str(STATE / "gallery-archive.sqlite3"))]
    cmd += ["--", url]
    print(f"[images] gallery-dl -> {out}")
    code, lines = run_stream(cmd, subprocess_env(proxy), ROOT, "gallery-dl", opts.verbose)
    files = collect_new_files(out, started_ts)
    if code != 0:
        tail = "\n".join(lines[-12:])
        raise DlError(f"gallery-dl exited {code}\n{tail}")
    if not files:
        raise DlError("gallery-dl finished but produced no new files (login/cookies may be required)")
    return Result(url, "images", True, out, files, sum(p.stat().st_size for p in files),
                  time.time() - started_ts)


def aria2_cmd(proxy: str | None, out: Path) -> list[str]:
    cmd = [
        str(ARIA2_EXE),
        "--dir", str(out),
        "--continue=true", "--auto-file-renaming=false", "--allow-overwrite=false",
        "--max-connection-per-server=8", "--split=8", "--min-split-size=1M",
        "--file-allocation=none", "--max-tries=10", "--retry-wait=2",
        "--connect-timeout=20", "--timeout=60",
        "--console-log-level=warn", "--summary-interval=5",
        "--download-result=hide",
        "--user-agent", UA,
    ]
    if proxy:
        cmd += ["--all-proxy", proxy]
    return cmd


def download_with_aria2(url: str, out: Path, proxy: str | None, opts: argparse.Namespace) -> Path:
    info = probe(url, proxy, insecure=opts.insecure)
    name = safe_name(opts.name) if opts.name else (info.filename or "download")
    # aria2's WinTLS backend cannot initialize in this restricted token; the
    # Python downloader is both reliable and resumable for HTTPS.
    if url.lower().startswith("https://"):
        return download_file(url, out, proxy, opts, name=name, info=info)
    cmd = aria2_cmd(proxy, out) + ["--out", name, url]
    print(f"[file] aria2 -> {out / name}")
    code, lines = run_stream(cmd, subprocess_env(proxy), ROOT, "aria2", opts.verbose)
    dest = out / name
    if code != 0 or not dest.exists():
        eprint(f"[warn] aria2 failed (exit {code}); falling back to Python downloader")
        return download_file(url, out, proxy, opts, name=name, info=info)
    return dest


def download_file(
    url: str, out: Path, proxy: str | None, opts: argparse.Namespace,
    name: str | None = None, info: Probe | None = None,
) -> Path:
    info = info or probe(url, proxy, insecure=opts.insecure)
    filename = safe_name(name or info.filename or "download")
    if not Path(filename).suffix and info.content_type:
        ext = {
            "application/zip": ".zip", "application/pdf": ".pdf",
            "application/x-7z-compressed": ".7z", "application/x-rar-compressed": ".rar",
            "video/mp4": ".mp4", "audio/mpeg": ".mp3", "image/jpeg": ".jpg",
            "image/png": ".png", "text/html": ".html", "text/plain": ".txt",
        }.get(info.content_type)
        if ext:
            filename += ext
    dest = out / filename
    part = out / (filename + ".part")
    total = info.length
    if dest.exists() and not opts.force:
        if not total or dest.stat().st_size == total:
            print(f"[file] already complete: {dest} ({human(dest.stat().st_size)})")
            return dest
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"}
    resume = part.exists() and part.stat().st_size > 0 and not opts.force
    if resume:
        headers["Range"] = f"bytes={part.stat().st_size}-"
    opener = build_opener(proxy, opts.insecure)
    req = urllib.request.Request(url, headers=headers)
    print(f"[file] {'resume' if resume else 'download'} -> {dest}")
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and part.exists():
            part.replace(dest)
            return dest
        raise DlError(f"HTTP {exc.code} for {url}") from exc
    with resp:
        if resume and getattr(resp, "status", 200) != 206:
            resume = False
            part.unlink(missing_ok=True)
        if total is None and resp.headers.get("Content-Length", "").isdigit():
            total = int(resp.headers["Content-Length"]) + (part.stat().st_size if resume else 0)
        mode = "ab" if resume else "wb"
        done = part.stat().st_size if resume else 0
        started = time.time()
        last = 0.0
        with open(part, mode) as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last >= 1.0:
                    speed = done / max(now - started, 0.001)
                    if total:
                        pct = done * 100 / total
                        print(f"\r  {pct:5.1f}%  {human(done)}/{human(total)}  {human(speed)}/s", end="", flush=True)
                    else:
                        print(f"\r  {human(done)}  {human(speed)}/s", end="", flush=True)
                    last = now
                if opts.limit_rate:
                    target = parse_rate(opts.limit_rate)
                    if target:
                        elapsed = time.time() - started
                        expected = done / target
                        if expected > elapsed:
                            time.sleep(min(expected - elapsed, 1.0))
        print()
    if total and part.stat().st_size < total:
        raise DlError(f"incomplete download: {human(part.stat().st_size)} of {human(total)}")
    part.replace(dest)
    return dest


def parse_rate(value: str) -> float | None:
    m = re.fullmatch(r"([\d.]+)\s*([KMG]?)", value.strip(), re.I)
    if not m:
        return None
    n = float(m.group(1))
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[m.group(2).upper()]
    return n * mult


def download_article(url: str, out: Path, proxy: str | None, opts: argparse.Namespace) -> Result:
    started_ts = time.time()
    if proxy:
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy
        os.environ["http_proxy"] = os.environ["https_proxy"] = proxy
    try:
        from trafilatura import extract, extract_metadata
    except Exception as exc:
        raise DlError(f"trafilatura is not installed: {exc}") from exc
    print(f"[article] fetch + extract -> {out}")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                          "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                          "Accept-Encoding": "identity"})
        with build_opener(proxy, opts.insecure).open(req, timeout=45) as resp:
            raw = resp.read(8 * 1024 * 1024)
            charset = resp.headers.get_content_charset()
        if not charset:
            m = re.search(rb"charset=[\"']?([\w-]+)", raw[:4096], re.I)
            charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
        html = raw.decode(charset, errors="replace")
    except Exception as exc:
        raise DlError(f"could not fetch the page: {exc}") from exc
    if not html:
        raise DlError("could not fetch the page (network, proxy, or anti-bot)")
    meta = extract_metadata(html)
    title = (meta.title if meta else None) or host_of(url) or "article"
    body = extract(
        html, url=url, output_format="markdown", include_links=True,
        include_images=False, favor_recall=True, with_metadata=False,
    )
    if not body or len(body.strip()) < 80:
        raise DlError("no readable article body found; try --mode file to save the raw page")
    prefix = datetime.now().strftime("%Y-%m-%d")
    if opts.name:
        path = out / (safe_name(opts.name) + ("" if opts.name.lower().endswith(".md") else ".md"))
    else:
        path = out / f"{prefix}-{slug(title)}.md"
    n = 2
    base_path = path
    while path.exists() and not opts.force:
        path = base_path.with_name(f"{base_path.stem}-{n}{base_path.suffix}")
        n += 1
    front = [
        "---",
        f"title: {json.dumps(str(title), ensure_ascii=False)}",
        f"url: {json.dumps(url, ensure_ascii=False)}",
    ]
    if meta:
        for key in ("author", "date", "sitename", "description"):
            val = getattr(meta, key, None)
            if val:
                front.append(f"{key}: {json.dumps(str(val), ensure_ascii=False)}")
    front += [f"fetched: {datetime.now().isoformat(timespec='seconds')}", "---", ""]
    path.write_text("\n".join(front) + body.strip() + "\n", encoding="utf-8")
    return Result(url, "article", True, out, [path], path.stat().st_size,
                  time.time() - started_ts, title=str(title))


def download_torrent(url: str, out: Path, proxy: str | None, opts: argparse.Namespace) -> Result:
    started_ts = time.time()
    target = url
    if url.lower().startswith("http") and parse_suffix(url) == ".torrent":
        torrents = STATE / "torrents"
        torrents.mkdir(parents=True, exist_ok=True)
        name = safe_name(opts.name or filename_from_url(url) or "download.torrent")
        target = str(download_file(url, torrents, proxy, opts, name=name))
    elif not url.lower().startswith("magnet:") and Path(url).exists():
        target = str(Path(url).resolve())
    cmd = [
        str(ARIA2_EXE), "--dir", str(out), "--seed-time=0",
        "--bt-stop-timeout=300", "--follow-torrent=mem",
        "--summary-interval=10", "--console-log-level=warn",
        "--max-tries=3", "--retry-wait=5", "--download-result=hide",
    ]
    if proxy:
        cmd += ["--all-proxy", proxy]
    cmd += [target]
    print(f"[torrent] aria2 -> {out}")
    code, lines = run_stream(cmd, subprocess_env(proxy), ROOT, "torrent", opts.verbose)
    files = collect_new_files(out, started_ts)
    if code != 0 and not files:
        tail = "\n".join(lines[-12:])
        raise DlError(f"aria2 torrent exited {code}\n{tail}")
    return Result(url, "torrent", True, out, files, sum(p.stat().st_size for p in files),
                  time.time() - started_ts)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def choose_out(cfg: dict, opts: argparse.Namespace) -> Path:
    if opts.out:
        out = Path(opts.out)
        if not out.is_absolute():
            out = ROOT / out
    else:
        out = ROOT / str(cfg.get("downloadRoot", "downloads"))
        if cfg.get("dateSubfolders", True) and not opts.flat:
            out = out / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def execute(url: str, mode: str, out: Path, proxy: str | None, cfg: dict, opts: argparse.Namespace) -> Result:
    actual = classify(url, proxy, cfg) if mode == "auto" else mode
    if opts.dry_run:
        print(f"[plan] {url}\n  mode: {actual}\n  out:  {out}")
        return Result(url, actual, True, out)
    if actual == "video":
        return download_video(url, out, proxy, cfg, opts)
    if actual == "audio":
        opts.quality = "audio"
        return download_video(url, out, proxy, cfg, opts)
    if actual == "images":
        return download_images(url, out, proxy, cfg, opts)
    if actual == "file":
        if opts.name and opts.name.lower().endswith((".mp4", ".mkv", ".webm", ".mp3")):
            return download_video(url, out, proxy, cfg, opts)
        dest = download_with_aria2(url, out, proxy, opts)
        return Result(url, "file", True, out, [dest], dest.stat().st_size)
    if actual == "article":
        return download_article(url, out, proxy, opts)
    if actual == "torrent":
        return download_torrent(url, out, proxy, opts)
    raise DlError(f"unknown mode: {actual}")


def record(result: Result) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), **result.as_dict()}
    with open(STATE / "history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_doctor(cfg: dict, opts: argparse.Namespace) -> int:
    print(f"root      {ROOT}")
    print(f"python    {sys.version.split()[0]}  ({sys.executable})")
    try:
        from importlib.metadata import version
        for pkg in ("yt-dlp", "gallery-dl", "trafilatura"):
            try:
                print(f"{pkg:<9} {version(pkg)}")
            except Exception:
                print(f"{pkg:<9} MISSING")
    except Exception:
        pass
    if (FFMPEG_DIR / "ffmpeg.exe").exists():
        try:
            out = subprocess.check_output([str(FFMPEG_DIR / "ffmpeg.exe"), "-version"], text=True, encoding="utf-8", errors="replace")
            print("ffmpeg    " + out.splitlines()[0])
        except Exception as exc:
            print(f"ffmpeg    ERROR {exc}")
    else:
        print("ffmpeg    MISSING")
    if ARIA2_EXE.exists():
        try:
            out = subprocess.check_output([str(ARIA2_EXE), "--version"], text=True, encoding="utf-8", errors="replace")
            print("aria2     " + out.splitlines()[0])
        except Exception as exc:
            print(f"aria2     ERROR {exc}")
    else:
        print("aria2     MISSING")
    print(f"node      {shutil.which('node') or 'MISSING'}")
    proxy = resolve_proxy(cfg, opts.no_proxy, opts.proxy)
    print(f"proxy     {proxy or 'direct'}")
    if proxy:
        hp = proxy_hostport(proxy)
        print(f"  tcp     {'OK' if hp and tcp_ok(proxy, 3) else 'FAIL'}")
        try:
            req = urllib.request.Request("http://www.gstatic.com/generate_204", headers={"User-Agent": UA})
            with build_opener(proxy).open(req, timeout=10) as r:
                print(f"  http    OK ({r.status})")
        except Exception as exc:
            print(f"  http    FAIL ({exc})")
    usage = shutil.disk_usage(ROOT)
    print(f"disk      {human(usage.free)} free of {human(usage.total)}")
    print(f"downloads {ROOT / cfg.get('downloadRoot', 'downloads')}")
    return 0


def cmd_update(cfg: dict, opts: argparse.Namespace) -> int:
    tmp = ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    env = subprocess_env(None)
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(tmp)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_CACHE_DIR"] = str(tmp / "pip-cache")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir",
           "--target", str(PYLIBS), "yt-dlp", "gallery-dl", "trafilatura", "--no-input"]
    proxy = resolve_proxy(cfg, opts.no_proxy, opts.proxy)
    if proxy:
        cmd += ["--proxy", proxy]
    print("[update] " + " ".join(cmd))
    proc = subprocess.run(cmd, env=env, cwd=str(ROOT))
    return proc.returncode


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("urls", nargs="+", help="URL(s), magnet link, or local .torrent file")
    p.add_argument("--mode", choices=["auto", "video", "audio", "images", "file", "article", "torrent"],
                   default="auto", help="force an engine (default: auto)")
    p.add_argument("--out", help="output directory (default: downloads/YYYY-MM-DD)")
    p.add_argument("--name", help="filename override (single URL only)")
    p.add_argument("--quality", default="best",
                   choices=["best", "2160", "1440", "1080", "720", "480", "audio"],
                   help="video quality cap (default: best)")
    p.add_argument("--audio-format", default="mp3", choices=["mp3", "m4a", "opus", "flac", "wav"])
    p.add_argument("--playlist", action="store_true", help="download the whole playlist")
    p.add_argument("--cookies", action="store_true", help="read cookies from the browser")
    p.add_argument("--browser", default=None, help="browser for cookies (edge, chrome, firefox, brave)")
    p.add_argument("--cookie-file", help="Netscape cookies.txt file")
    p.add_argument("--subs", action="store_true", help="download and embed subtitles")
    p.add_argument("--force", action="store_true", help="ignore archives and overwrite")
    p.add_argument("--flat", action="store_true", help="do not add the date subfolder")
    p.add_argument("--proxy", help="proxy URL (default: auto-detect)")
    p.add_argument("--no-proxy", action="store_true", help="connect directly")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification (unsafe)")
    p.add_argument("--limit-rate", help="e.g. 2M")
    p.add_argument("--dry-run", action="store_true", help="show the engine and destination only")
    p.add_argument("--json", action="store_true", help="print a JSON summary")
    p.add_argument("-v", "--verbose", action="store_true")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"doctor", "update", "get", "video", "audio", "images", "file", "article", "torrent"}
    if not argv:
        argv = ["--help"]
    elif argv[0] not in commands and not argv[0].startswith("-"):
        argv.insert(0, "get")

    parser = argparse.ArgumentParser(
        prog="dl",
        description="Download video, audio, images, files, articles, and torrents.",
    )
    parser.add_argument("--version", action="version", version="dsh-download 1.0")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="check engines, proxy, and disk")
    p_doc.add_argument("--proxy")
    p_doc.add_argument("--no-proxy", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_up = sub.add_parser("update", help="update yt-dlp / gallery-dl / trafilatura")
    p_up.add_argument("--proxy")
    p_up.add_argument("--no-proxy", action="store_true")
    p_up.set_defaults(func=cmd_update)

    for name in ("get", "video", "audio", "images", "file", "article", "torrent"):
        p = sub.add_parser(name, help=f"download as {name}")
        add_common(p)
        p.set_defaults(func=None, forced_mode=name)

    args = parser.parse_args(argv)
    cfg = load_config()
    if hasattr(args, "browser") and args.browser is None:
        args.browser = cfg.get("browser", "edge")

    if args.func is not None:
        return args.func(cfg, args)

    if args.name and len(args.urls) > 1:
        eprint("[error] --name can only be used with one URL")
        return 2

    mode = args.mode
    if args.forced_mode != "get":
        mode = args.forced_mode
    proxy = resolve_proxy(cfg, args.no_proxy, args.proxy)
    STATE.mkdir(parents=True, exist_ok=True)
    out = choose_out(cfg, args)
    results: list[Result] = []
    failed = 0
    for url in args.urls:
        started = time.time()
        print(f"\n[url] {url}")
        try:
            res = execute(url, mode, out, proxy, cfg, args)
            res.seconds = res.seconds or (time.time() - started)
            record(res)
            results.append(res)
            if not args.dry_run:
                if res.files:
                    for f in res.files:
                        print(f"[saved] {f}")
                    print(f"[ok] {len(res.files)} file(s), {human(res.bytes)}, {res.seconds:.1f}s")
                else:
                    print("[ok] finished (no new files; already archived?)")
        except KeyboardInterrupt:
            eprint("\n[interrupted]")
            return 130
        except Exception as exc:
            failed += 1
            msg = str(exc)
            eprint(f"[error] {msg}")
            res = Result(url, mode, False, out, error=msg, seconds=time.time() - started)
            record(res)
            results.append(res)

    if args.json:
        print(json.dumps([r.as_dict() for r in results], ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
