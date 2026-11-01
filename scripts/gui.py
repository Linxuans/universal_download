#!/usr/bin/env python3
"""FetchDesk desktop shell.

A small local HTTP server serves the HTML/CSS/JS UI and exposes the download
API. The window is Microsoft Edge in ``--app`` mode with a dedicated profile,
so it looks like a standalone application without a browser address bar.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
PYLIBS = ROOT / "tools" / "pylibs"
DL = ROOT / ".dsh" / "skills" / "download" / "scripts" / "dl.py"
STATE = ROOT / "state"
GUI_STATE = STATE / "gui"
CONFIG = ROOT / "config.json"
GUI_DIR = ROOT / "gui"
LOG = STATE / "gui.log"
VERSION = "2.0.1"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

if str(PYLIBS) not in sys.path:
    sys.path.insert(0, str(PYLIBS))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
try:
    import scout as scout_core
except Exception as exc:  # surfaced by the API method
    scout_core = None
    SCOUT_ERROR = exc
else:
    SCOUT_ERROR = None

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def log(message: str) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def load_dl():
    spec = importlib.util.spec_from_file_location("dlcore", DL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["dlcore"] = module
    spec.loader.exec_module(module)
    return module


def read_config() -> dict:
    base = {
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
    if CONFIG.exists():
        try:
            base.update(json.loads(CONFIG.read_text(encoding="utf-8-sig")))
        except Exception as exc:
            log(f"config read failed: {exc}")
    return base


def write_config(data: dict) -> None:
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG)


def human_bytes(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


class Api:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.job_map: dict[str, dict] = {}
        self.dl = load_dl()
        self.config = read_config()
        self._status_cache: tuple[float, dict] | None = None
        GUI_STATE.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # status / config
    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        now = time.time()
        if self._status_cache and now - self._status_cache[0] < 20:
            return self._status_cache[1]
        engines = []
        for package, label in (("yt-dlp", "yt-dlp"), ("gallery-dl", "gallery-dl"), ("trafilatura", "trafilatura")):
            try:
                from importlib.metadata import version
                engines.append({"name": label, "version": version(package), "ok": True})
            except Exception:
                engines.append({"name": label, "version": "未安装", "ok": False})
        ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        aria2 = ROOT / "tools" / "aria2" / "aria2c.exe"
        engines.append({"name": "ffmpeg", "version": self._binary_version(ffmpeg), "ok": ffmpeg.exists()})
        engines.append({"name": "aria2", "version": self._binary_version(aria2), "ok": aria2.exists()})
        proxy = self.dl.resolve_proxy(self.config, False, None)
        usage = shutil.disk_usage(ROOT)
        active = sum(1 for j in self.job_map.values() if j["status"] in ("queued", "running"))
        data = {
            "ok": True,
            "engines": engines,
            "proxy": proxy or "直连",
            "proxy_ok": bool(proxy and self.dl.tcp_ok(proxy, 2)),
            "node": shutil.which("node") or "",
            "disk_free": usage.free,
            "disk_total": usage.total,
            "download_root": str(self._download_root()),
            "config": self.config,
            "active": active,
            "jobs": len(self.job_map),
            "version": VERSION,
        }
        self._status_cache = (now, data)
        return data

    def _binary_version(self, path: Path) -> str:
        if not path.exists():
            return "未安装"
        try:
            out = subprocess.check_output(
                [str(path), "-version" if path.name.startswith("ffmpeg") else "--version"],
                text=True, encoding="utf-8", errors="replace", timeout=6,
                creationflags=CREATE_NO_WINDOW,
            )
            return out.splitlines()[0].strip()[:80]
        except Exception:
            return "已安装"

    def _download_root(self) -> Path:
        value = Path(str(self.config.get("downloadRoot", "downloads")))
        return value if value.is_absolute() else ROOT / value

    def scout(self, payload: dict) -> dict:
        payload = payload or {}
        goal = str(payload.get("goal") or "").strip()
        if len(goal) < 2:
            return {"ok": False, "error": "请描述你要做的项目或功能"}
        if scout_core is None:
            return {"ok": False, "error": f"Scout 未加载：{SCOUT_ERROR}"}
        try:
            result = scout_core.advise(
                goal,
                limit=int(payload.get("limit") or 5),
                refresh=bool(payload.get("refresh")),
                no_token=bool(payload.get("no_token")),
            )
        except Exception as exc:
            log("scout failed: " + repr(exc))
            return {"ok": False, "error": str(exc)}
        result["ok"] = True
        return result

    def save_config(self, payload: dict) -> dict:
        allowed = {
            "proxy", "autoProxy", "downloadRoot", "dateSubfolders", "browser",
            "retries", "fragments", "embedMetadata", "writeSubtitles",
        }
        with self.lock:
            for key, value in (payload or {}).items():
                if key in allowed:
                    self.config[key] = value
            write_config(self.config)
            self._status_cache = None
        return {"ok": True, "config": self.config, "status": self.status()}

    def pick_folder(self) -> str | None:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(initialdir=str(self._download_root()))
            root.destroy()
            return path or None
        except Exception as exc:
            log(f"pick_folder failed: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # jobs
    # ------------------------------------------------------------------ #
    def start(self, payload: dict) -> dict:
        payload = payload or {}
        url = str(payload.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "请先粘贴一个链接"}
        if not re.match(r"^(https?://|magnet:)", url, re.I):
            url = "https://" + url
        mode = str(payload.get("mode") or "auto")
        if mode not in {"auto", "video", "audio", "images", "file", "article", "torrent"}:
            return {"ok": False, "error": "未知的下载类型"}
        quality = str(payload.get("quality") or "best")
        if quality not in {"best", "2160", "1440", "1080", "720", "480", "audio"}:
            quality = "best"
        job_id = uuid.uuid4().hex[:10]
        progress_path = GUI_STATE / f"{job_id}.json"
        job = {
            "id": job_id,
            "url": url,
            "mode": mode,
            "status": "queued",
            "percent": 0,
            "phase": "排队中",
            "done": 0,
            "total": 0,
            "speed": 0,
            "files": [],
            "error": "",
            "started": time.time(),
            "ended": 0,
            "log_tail": [],
            "pid": 0,
            "title": "",
        }
        child_python = sys.executable
        if child_python.lower().endswith("pythonw.exe"):
            candidate = Path(child_python).with_name("python.exe")
            if candidate.exists():
                child_python = str(candidate)
        cmd = [child_python, str(DL), "get" if mode == "auto" else mode]
        if mode in ("auto", "video"):
            cmd += ["--quality", quality]
        if payload.get("audio_format"):
            cmd += ["--audio-format", str(payload["audio_format"])]
        if payload.get("playlist"):
            cmd += ["--playlist"]
        if payload.get("cookies"):
            cmd += ["--cookies", "--browser", str(payload.get("browser") or self.config.get("browser") or "edge")]
        if payload.get("cookie_file"):
            cmd += ["--cookie-file", str(payload["cookie_file"])]
        if payload.get("subs"):
            cmd += ["--subs"]
        if payload.get("force"):
            cmd += ["--force"]
        if payload.get("flat"):
            cmd += ["--flat"]
        if payload.get("name"):
            cmd += ["--name", str(payload["name"])]
        if payload.get("out"):
            cmd += ["--out", str(payload["out"])]
        if payload.get("limit_rate"):
            cmd += ["--limit-rate", str(payload["limit_rate"])]
        cmd += ["--json", "--progress-file", str(progress_path), "--", url]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYLIBS) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PATH"] = str(ROOT / "tools" / "ffmpeg" / "bin") + os.pathsep + str(ROOT / "tools" / "aria2") + os.pathsep + env.get("PATH", "")
        with self.lock:
            self.job_map[job_id] = job
        threading.Thread(target=self._run, args=(job, cmd, env, progress_path), daemon=True).start()
        return {"ok": True, "job": self._snapshot(job)}

    def _run(self, job: dict, cmd: list[str], env: dict, progress_path: Path) -> None:
        log("start " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
            with self.lock:
                job["pid"] = proc.pid
                job["status"] = "running"
                job["phase"] = "启动引擎"
            chunks: list[str] = []

            def reader() -> None:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = ANSI_RE.sub("", raw.rstrip("\r\n"))
                    if not line:
                        continue
                    chunks.append(line)
                    with self.lock:
                        job["log_tail"].append(line)
                        if len(job["log_tail"]) > 160:
                            job["log_tail"] = job["log_tail"][-160:]
                        if line.startswith("[saved]"):
                            path = line[len("[saved]"):].strip()
                            if path and path not in job["files"]:
                                job["files"].append(path)
                        if line.startswith("[error]"):
                            job["error"] = line[len("[error]"):].strip()

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            while proc.poll() is None:
                self._read_progress(job, progress_path)
                time.sleep(0.25)
            thread.join(timeout=3)
            self._read_progress(job, progress_path)
            code = proc.returncode
            self._parse_json_result(job, chunks)
            with self.lock:
                job["ended"] = time.time()
                if job["error"]:
                    job["status"] = "error"
                elif code == 0:
                    job["status"] = "done"
                    job["percent"] = 100
                    job["phase"] = "完成"
                else:
                    job["status"] = "error"
                    job["error"] = job["error"] or f"引擎退出码 {code}"
                    job["phase"] = "失败"
            log(f"end {job['id']} code={code} status={job['status']}")
        except Exception as exc:
            log("job crashed: " + repr(exc))
            with self.lock:
                job["status"] = "error"
                job["error"] = str(exc)
                job["phase"] = "失败"
                job["ended"] = time.time()

    def _read_progress(self, job: dict, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        with self.lock:
            if data.get("percent") is not None:
                job["percent"] = max(0.0, min(100.0, float(data["percent"])))
            if data.get("done") is not None:
                job["done"] = data.get("done") or 0
            if data.get("total") is not None:
                job["total"] = data.get("total") or 0
            if data.get("speed") is not None:
                job["speed"] = data.get("speed") or 0
            if data.get("phase"):
                job["phase"] = str(data["phase"])

    def _parse_json_result(self, job: dict, chunks: list[str]) -> None:
        text = "\n".join(chunks)
        marker = text.rfind("\n[\n")
        if marker < 0 and text.lstrip().startswith("["):
            candidate = text[text.find("["):]
        else:
            candidate = text[marker + 1:] if marker >= 0 else ""
        if not candidate:
            return
        try:
            data = json.loads(candidate)
        except Exception:
            return
        if not isinstance(data, list):
            return
        files: list[str] = []
        errors: list[str] = []
        total = 0
        title = ""
        for item in data:
            if not isinstance(item, dict):
                continue
            for path in item.get("files") or []:
                if path not in files:
                    files.append(path)
            total += int(item.get("bytes") or 0)
            title = item.get("title") or title
            if item.get("error"):
                errors.append(str(item["error"]))
            if item.get("mode"):
                job["mode"] = item["mode"]
        with self.lock:
            if files:
                job["files"] = files
            if total:
                job["done"] = total
            if title:
                job["title"] = title
            if errors:
                job["error"] = errors[-1]

    def _snapshot(self, job: dict) -> dict:
        with self.lock:
            data = dict(job)
            data["elapsed"] = round((data.get("ended") or time.time()) - data["started"], 1)
            data["log_tail"] = data.get("log_tail", [])[-60:]
            data["done_text"] = human_bytes(data.get("done"))
            data["total_text"] = human_bytes(data.get("total"))
            data["speed_text"] = human_bytes(data.get("speed")) + "/s" if data.get("speed") else ""
            return data

    def jobs(self) -> list[dict]:
        with self.lock:
            items = [self._snapshot(j) for j in self.job_map.values()]
        items.sort(key=lambda j: j["started"], reverse=True)
        return items

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.job_map.get(job_id)
            pid = job.get("pid") if job else 0
        if not job or job["status"] not in ("queued", "running"):
            return {"ok": False, "error": "任务已结束"}
        if pid:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            except Exception as exc:
                log(f"cancel failed: {exc}")
        with self.lock:
            job["status"] = "cancelled"
            job["phase"] = "已取消"
            job["ended"] = time.time()
        return {"ok": True}

    def clear_finished(self) -> dict:
        with self.lock:
            keep = {k: v for k, v in self.job_map.items() if v["status"] in ("queued", "running")}
            removed = len(self.job_map) - len(keep)
            self.job_map = keep
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------ #
    # history / shell
    # ------------------------------------------------------------------ #
    def history(self, limit: int = 50) -> list[dict]:
        path = STATE / "history.jsonl"
        if not path.exists():
            return []
        entries = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    item["bytes_text"] = human_bytes(item.get("bytes"))
                    item["exists"] = any(Path(p).exists() for p in item.get("files") or [])
                    entries.append(item)
        except Exception as exc:
            log(f"history read failed: {exc}")
        return list(reversed(entries[-int(limit or 50):]))

    def open_path(self, path: str) -> dict:
        try:
            target = Path(str(path))
            if not target.is_absolute():
                target = ROOT / target
            if not target.exists():
                return {"ok": False, "error": "路径不存在"}
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)], creationflags=CREATE_NO_WINDOW)
            else:
                os.startfile(str(target))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_downloads(self) -> dict:
        root = self._download_root()
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(root))
        return {"ok": True}

    def read_clipboard(self) -> str:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.update()
            value = root.clipboard_get()
            root.destroy()
            return value or ""
        except Exception:
            return ""


class Handler(BaseHTTPRequestHandler):
    api: Api
    token: str
    server_version = "FetchDesk/1.1"

    def log_message(self, fmt, *args):  # keep the console quiet
        log("http " + fmt % args)

    def _authorized(self) -> bool:
        return self.headers.get("X-FetchDesk-Token", "") == self.token

    def _send_json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".png": "image/png",
                ".ico": "image/x-icon", ".svg": "image/svg+xml"}.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            token = parse_qs(parsed.query).get("token", [""])[0]
            if token != self.token:
                self._send_json({"ok": False, "error": "invalid token"}, 403)
                return
            self._send_file(GUI_DIR / "index.html")
            return
        if parsed.path == "/favicon.ico":
            icon = GUI_DIR / "assets" / "icon.png"
            if icon.exists():
                self._send_file(icon)
            else:
                self.send_error(404)
            return
        rel = parsed.path.lstrip("/")
        target = (GUI_DIR / rel).resolve()
        if not str(target).startswith(str(GUI_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        self._send_file(target)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json({"ok": False, "error": "invalid token"}, 403)
            return
        parsed = urlparse(self.path)
        name = parsed.path.rsplit("/", 1)[-1]
        method = getattr(self.api, name, None)
        if not callable(method) or name.startswith("_"):
            self._send_json({"ok": False, "error": "unknown method"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2 * 1024 * 1024:
                self._send_json({"ok": False, "error": "payload too large"}, 413)
                return
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body.decode("utf-8") or "{}")
            args = data.get("args", [])
            if not isinstance(args, list):
                args = [args]
            result = method(*args)
            self._send_json(result)
        except Exception as exc:
            log("api error: " + traceback.format_exc())
            self._send_json({"ok": False, "error": str(exc)}, 500)


def find_edge() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return shutil.which("msedge")


def main() -> int:
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    Handler.api = Api()
    Handler.token = token
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={token}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"serving {url}")

    if "--serve-only" in sys.argv:
        print(url, flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0

    edge = find_edge()
    if not edge:
        webbrowser.open(url)
        log("edge not found; opened default browser")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0

    profile = STATE / "edge-profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        edge,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-features=msEdgeFirstRunExperience,Translate",
        "--disable-sync",
        "--window-size=1180,780",
    ]
    log("launch " + " ".join(cmd))
    proc = subprocess.Popen(cmd)
    try:
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        code = None
    if code not in (None, 0):
        log(f"edge exited early with {code}; falling back to default browser")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        if code is None:
            proc.wait()
        server.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("fatal:\n" + traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "下载工作台启动失败，详情见 state\\gui.log", "下载工作台", 0x10)
        except Exception:
            pass
        raise