#!/usr/bin/env python3
"""Recreate the portable parts of the download workbench.

The repository intentionally keeps binaries and downloaded packages out of Git.
This script installs the Python engines into ``tools/pylibs`` and fetches the
pinned ffmpeg/aria2 Windows builds into ``tools``. It uses only the standard
library so it can run before any dependency is installed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PYLIBS = TOOLS / "pylibs"
REQUIREMENTS = ROOT / "requirements.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dsh-download-setup/1.0"

FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
ARIA2_URL = "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip"


def log(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def proxy_from_env() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            return value if "://" in value else "http://" + value
    return None


def opener(proxy: str | None):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def download(url: str, dest: Path, proxy: str | None, retries: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            log(f"download {url} (attempt {attempt}/{retries})")
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with opener(proxy).open(req, timeout=90) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(part, "wb") as fh:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if total and done % (1024 * 1024 * 20) < 1024 * 256:
                            log(f"  {done / 1048576:.0f}/{total / 1048576:.0f} MB")
            part.replace(dest)
            log(f"  saved {dest} ({dest.stat().st_size / 1048576:.1f} MB)")
            return
        except Exception as exc:
            last_error = exc
            log(f"  failed: {exc}")
            part.unlink(missing_ok=True)
    fail(f"could not download {url}: {last_error}")


def run(cmd: list[str], env: dict | None = None) -> None:
    log("run " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode:
        fail(f"command failed with exit code {proc.returncode}")


def install_python(proxy: str | None, force: bool) -> None:
    if not REQUIREMENTS.exists():
        fail(f"missing {REQUIREMENTS.name}")
    tmp = ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(tmp)
    env["PIP_CACHE_DIR"] = str(tmp / "pip-cache")
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    cmd = [
        sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir",
        "--target", str(PYLIBS), "-r", str(REQUIREMENTS), "--no-input",
    ]
    if force:
        cmd.insert(4, "--force-reinstall")
    if proxy:
        cmd += ["--proxy", proxy]
    run(cmd, env)


def unpack(zip_path: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


def install_ffmpeg(proxy: str | None, force: bool) -> None:
    bin_dir = TOOLS / "ffmpeg" / "bin"
    exe = bin_dir / "ffmpeg.exe"
    probe = bin_dir / "ffprobe.exe"
    if exe.exists() and probe.exists() and not force:
        log(f"ffmpeg already present: {exe}")
        return
    tmp = ROOT / ".tmp"
    zpath = tmp / "ffmpeg.zip"
    download(FFMPEG_URL, zpath, proxy)
    unpack(zpath, tmp / "ffmpeg-unpack")
    found = list((tmp / "ffmpeg-unpack").rglob("ffmpeg.exe"))
    if not found:
        fail("ffmpeg.exe not found in the downloaded archive")
    src_bin = found[0].parent
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        src = src_bin / name
        if not src.exists():
            fail(f"{name} missing from the downloaded build")
        shutil.copy2(src, bin_dir / name)
        log(f"installed {bin_dir / name}")
    zpath.unlink(missing_ok=True)
    shutil.rmtree(tmp / "ffmpeg-unpack", ignore_errors=True)


def install_aria2(proxy: str | None, force: bool) -> None:
    dest = TOOLS / "aria2"
    exe = dest / "aria2c.exe"
    if exe.exists() and not force:
        log(f"aria2 already present: {exe}")
        return
    tmp = ROOT / ".tmp"
    zpath = tmp / "aria2.zip"
    download(ARIA2_URL, zpath, proxy)
    unpack(zpath, tmp / "aria2-unpack")
    found = list((tmp / "aria2-unpack").rglob("aria2c.exe"))
    if not found:
        fail("aria2c.exe not found in the downloaded archive")
    src_dir = found[0].parent
    dest.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, dest / item.name)
    log(f"installed {exe}")
    zpath.unlink(missing_ok=True)
    shutil.rmtree(tmp / "aria2-unpack", ignore_errors=True)


def check(proxy: str | None) -> int:
    ok = True
    print(f"root       {ROOT}")
    print(f"python     {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        print("python     NEEDS 3.10+")
        ok = False
    sys.path.insert(0, str(PYLIBS))
    try:
        from importlib.metadata import version
        for pkg in ("yt-dlp", "gallery-dl", "trafilatura"):
            try:
                print(f"{pkg:<10} {version(pkg)}")
            except Exception:
                print(f"{pkg:<10} MISSING")
                ok = False
    except Exception:
        ok = False
    ffmpeg = TOOLS / "ffmpeg" / "bin" / "ffmpeg.exe"
    aria2 = TOOLS / "aria2" / "aria2c.exe"
    print(f"ffmpeg     {'OK' if ffmpeg.exists() else 'MISSING'}  {ffmpeg}")
    print(f"aria2      {'OK' if aria2.exists() else 'MISSING'}  {aria2}")
    if not ffmpeg.exists() or not aria2.exists():
        ok = False
    print(f"proxy      {proxy or 'direct'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the download workbench dependencies")
    parser.add_argument("--proxy", help="HTTP proxy, for example http://127.0.0.1:7890")
    parser.add_argument("--no-proxy", action="store_true", help="connect directly")
    parser.add_argument("--check", action="store_true", help="report status without installing")
    parser.add_argument("--force", action="store_true", help="reinstall packages and binaries")
    args = parser.parse_args()
    proxy = None if args.no_proxy else (args.proxy or proxy_from_env())
    if args.check:
        return check(proxy)
    if sys.version_info < (3, 10):
        fail("Python 3.10 or newer is required")
    TOOLS.mkdir(parents=True, exist_ok=True)
    (ROOT / ".tmp").mkdir(exist_ok=True)
    install_python(proxy, args.force)
    install_ffmpeg(proxy, args.force)
    install_aria2(proxy, args.force)
    print()
    print("Done. Next:")
    print("  dl.cmd doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())