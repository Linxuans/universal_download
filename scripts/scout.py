#!/usr/bin/env python3
"""Scout: recommend Agent Skills and DSH plugins for a stated goal.

Read-only by design. It searches GitHub and the public DSH plugin registry,
reads SKILL.md files for evidence, scores candidates, and prints a Markdown or
JSON report. Installation belongs to a later iteration.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
CONFIG = ROOT / "config.json"
CACHE = STATE / "scout" / "cache.json"
PLUGIN_CACHE = STATE / "scout" / "plugins.json"
DSH_HOME = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
PLUGIN_REGISTRY_URL = "https://awesome-dsh-plugin.com/plugins.json"
UA = "FetchDesk-Scout/2.0"
CACHE_TTL = 24 * 3600
CACHE_SCHEMA = "2.0.2"
PLUGIN_TTL = 24 * 3600
MAX_REPOS = 9
MAX_CODE_RESULTS = 10

SKILL_HINTS = ("skill", "skills", "agent", "claude", "codex", "workflow")
PLUGIN_HINTS = ("dsh", "deepseek harness", "deepseek-harness", "dsh-plugin")

SYNONYMS = {
    "下载": ["download", "fetch", "save"],
    "游戏": ["game", "gaming", "gamedev", "unity", "godot", "unreal"],
    "小说": ["novel", "fiction", "story", "writing", "book"],
    "写作": ["writing", "author", "content"],
    "开发": ["develop", "development", "build", "coding"],
    "视频": ["video", "movie", "media"],
    "音频": ["audio", "sound", "music"],
    "图片": ["image", "photo", "picture", "gallery"],
    "文章": ["article", "blog", "post", "markdown"],
    "网页": ["web", "website", "page", "html"],
    "爬虫": ["crawler", "scrape", "scraping", "crawl"],
    "表格": ["excel", "xlsx", "spreadsheet", "csv"],
    "报表": ["report", "spreadsheet"],
    "文档": ["document", "docx", "word", "pdf"],
    "幻灯片": ["ppt", "pptx", "slide", "presentation"],
    "数据库": ["database", "db", "sql", "postgres", "mysql"],
    "测试": ["test", "testing", "qa"],
    "部署": ["deploy", "deployment", "ci", "cd"],
    "代码": ["code", "coding", "programming"],
    "审查": ["review", "audit", "lint"],
    "翻译": ["translate", "translation", "i18n"],
    "识别": ["ocr", "recognize", "vision"],
    "转换": ["convert", "conversion", "transform"],
    "压缩": ["compress", "zip", "archive"],
    "字幕": ["subtitle", "captions", "srt"],
    "剪辑": ["edit", "editing", "cut"],
    "报告": ["report", "summary", "dashboard"],
    "自动化": ["automation", "automate", "workflow"],
    "插件": ["plugin", "extension"],
    "技能": ["skill", "skills"],
    "通知": ["notification", "notify", "alert"],
    "微信": ["wechat", "weixin"],
    "飞书": ["feishu", "lark"],
    "钉钉": ["dingtalk"],
    "邮件": ["email", "mail"],
    "浏览器": ["browser", "chrome", "edge"],
    "终端": ["terminal", "shell", "tui"],
    "搜索": ["search", "find"],
    "记忆": ["memory", "context"],
    "代理": ["agent", "proxy"],
    "模型": ["model", "llm"],
    "图表": ["chart", "diagram", "graph"],
    "设计": ["design", "ui", "ux"],
    "安全": ["security", "audit", "vulnerability"],
    "推荐": ["recommend", "suggest"],
}

ACTIONS = {
    "下载": ["download", "save", "rip", "grab"],
    "提取": ["extract", "demux", "transcribe", "transcription"],
    "转换": ["convert", "transform", "export"],
    "生成": ["generate", "create", "produce"],
    "总结": ["summarize", "summary", "digest"],
    "分析": ["analyze", "analysis", "inspect"],
    "抓取": ["scrape", "crawl", "harvest"],
    "搜索": ["search", "find"],
    "安装": ["install", "setup"],
    "部署": ["deploy", "deployment"],
    "测试": ["test", "testing"],
    "编辑": ["edit", "editing"],
    "制作": ["create", "make", "build"],
    "自动化": ["automate", "automation", "workflow"],
    "通知": ["notify", "notification", "alert"],
    "开发": ["develop", "build", "create"],
    "写": ["write", "writing", "author"],
}

ENTITIES = {
    "bilibili": ("b站", "bilibili", "哔哩哔哩"),
    "youtube": ("youtube", "油管"),
    "pixiv": ("pixiv", "p站"),
    "wechat": ("微信", "wechat", "weixin", "公众号"),
    "feishu": ("飞书", "feishu", "lark"),
    "dingtalk": ("钉钉", "dingtalk"),
    "douyin": ("抖音", "douyin", "tiktok"),
    "xiaohongshu": ("小红书", "xiaohongshu", "rednote"),
    "zhihu": ("知乎", "zhihu"),
    "github": ("github",),
    "reddit": ("reddit",),
    "twitter": ("twitter", "x.com"),
    "instagram": ("instagram",),
    "notion": ("notion",),
    "obsidian": ("obsidian",),
    "telegram": ("telegram",),
}

STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from",
    "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "that",
    "the", "this", "to", "want", "with", "you", "your", "一个", "我要", "我想",
    "可以", "需要", "实现", "功能", "项目", "用于", "能够", "这个", "帮我",
}

RISK_PATTERNS = [
    (re.compile(r"curl[^\n|]*\|\s*(ba)?sh", re.I), "包含 curl | sh 远程执行"),
    (re.compile(r"iwr[^\n|]*\|\s*iex", re.I), "包含 PowerShell 远程执行"),
    (re.compile(r"powershell[^\n]*-enc(odedcommand)?\b", re.I), "包含编码 PowerShell 命令"),
    (re.compile(r"rm\s+-rf\s+[/~]", re.I), "包含危险的递归删除"),
    (re.compile(r"base64\s+-d[^\n|]*\|\s*(ba)?sh", re.I), "包含 base64 解码后执行"),
    (re.compile(r"os\.system\(|subprocess\.(run|Popen|call)\(", re.I), "脚本可能执行系统命令"),
    (re.compile(r"eval\(|exec\(", re.I), "脚本可能动态执行代码"),
]


class ScoutError(RuntimeError):
    pass


@dataclass
class Candidate:
    kind: str
    name: str
    url: str
    description: str = ""
    stars: int = 0
    pushed_at: str = ""
    license: str = ""
    owner: str = ""
    path: str = ""
    installs: int = 0
    source: str = ""
    install: str = ""
    relevance: float = 0.0
    score: float = 0.0
    compatibility: float = 0.0
    trust: float = 0.0
    freshness: float = 1.0
    popularity: float = 0.0
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    verified: bool = False
    installed: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        data = {
            "kind": self.kind,
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "stars": self.stars,
            "pushed_at": self.pushed_at,
            "license": self.license,
            "owner": self.owner,
            "path": self.path,
            "installs": self.installs,
            "source": self.source,
            "install": self.install,
            "relevance": round(self.relevance, 3),
            "score": round(self.score, 3),
            "compatibility": round(self.compatibility, 3),
            "trust": round(self.trust, 3),
            "freshness": round(self.freshness, 3),
            "popularity": round(self.popularity, 3),
            "reasons": self.reasons,
            "risks": self.risks,
            "tags": self.tags,
            "verified": self.verified,
            "installed": self.installed,
            "extra": self.extra,
        }
        return data


# --------------------------------------------------------------------------- #
# text / relevance
# --------------------------------------------------------------------------- #

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def goal_terms(goal: str) -> list[str]:
    text = normalize(goal)
    terms: list[str] = []
    # Direct English words in the user's goal are the strongest signal.
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#._-]{1,}", text):
        token = token.strip("._-").lower()
        if len(token) >= 2 and token not in STOP and token not in terms:
            terms.append(token)
    for zh, en in SYNONYMS.items():
        if zh in text:
            for value in en:
                if value not in terms:
                    terms.append(value)
    aliases = {
        "excel": ["xlsx", "spreadsheet"],
        "word": ["docx"],
        "powerpoint": ["pptx", "ppt"],
        "pdf": ["pdf"],
    }
    for term in list(terms):
        for alias in aliases.get(term, []):
            if alias not in terms:
                terms.append(alias)
    # Chinese bigrams help match Chinese descriptions when no English synonym exists.
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in STOP and bg not in terms:
                terms.append(bg)
    return terms[:18]


def goal_profile(goal: str) -> dict:
    text = normalize(goal)
    compact = re.sub(r"\s+", "", text)
    terms = goal_terms(goal)
    actions: list[str] = []
    action_zh: list[str] = []
    for zh, values in ACTIONS.items():
        if zh in text:
            action_zh.append(zh)
            for value in values:
                if value not in actions:
                    actions.append(value)
    for value in ("download", "fetch", "extract", "convert", "generate", "summarize", "scrape", "crawl", "search", "install", "deploy", "test", "edit", "automate", "notify"):
        if value in text and value not in actions:
            actions.append(value)
    # Chinese inflections that do not literally contain the ACTIONS key.
    inflections = {
        "convert": ("转成", "转为", "转换成", "转换", "导出为"),
        "extract": ("提取", "抽取", "摘出"),
        "download": ("下载", "保存到", "保存"),
        "generate": ("生成", "制作"),
        "summarize": ("总结", "摘要", "汇总"),
        "scrape": ("抓取", "爬取"),
    }
    for action, words in inflections.items():
        if any(word in text for word in words) and action not in actions:
            actions.append(action)
    entities: list[str] = []
    entity_terms: list[str] = []
    for key, aliases in ENTITIES.items():
        if any(alias in text or alias in compact for alias in aliases):
            entities.append(key)
            entity_terms.append(key)
            entity_terms.extend(aliases)
    content = [t for t in terms if t not in actions and t not in entities]
    return {
        "terms": terms,
        "actions": actions,
        "action_zh": action_zh,
        "entities": entities,
        "entity_terms": list(dict.fromkeys(entity_terms)),
        "content": content,
    }


def has_strong_match(profile: dict, *texts: str) -> bool:
    blob = normalize(" ".join(str(t or "") for t in texts))
    actions = profile.get("actions") or []
    action_zh = profile.get("action_zh") or []
    entities = profile.get("entities") or []
    entity_terms = profile.get("entity_terms") or []
    content = profile.get("content") or []
    if not actions and not entities:
        return True
    action_hit = any(a in blob for a in actions) or any(a in blob for a in action_zh)
    entity_hit = any(e in blob for e in (entity_terms or entities))
    content_hit = any(c in blob for c in content)
    if content or entities:
        if not (content_hit or entity_hit):
            return False
        if actions and not (action_hit or entity_hit):
            return False
        return True
    return action_hit or not actions


def term_in(term: str, blob: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9+#._-]+", term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", blob) is not None
    return term in blob


def relevance(terms: list[str], *texts: str) -> float:
    if not terms:
        return 0.0
    blob = normalize(" ".join(texts))
    if not blob:
        return 0.0
    hits = 0.0
    for term in terms:
        if term_in(term, blob):
            hits += 1.0
        elif len(term) >= 4 and term[:4] in blob:
            hits += 0.4
    denom = max(3, min(len(terms), 8))
    value = hits / denom
    # Exact phrase bonuses.
    phrase = " ".join(terms[:3])
    if len(phrase) >= 6 and phrase in blob:
        value += 0.15
    return max(0.0, min(1.0, value))


def freshness(pushed_at: str) -> float:
    if not pushed_at:
        return 0.4
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except Exception:
        return 0.4
    if days <= 90:
        return 1.0
    if days <= 365:
        return 0.8
    if days <= 730:
        return 0.5
    return 0.2


def popularity(stars: int) -> float:
    return min(1.0, math.log10(max(0, int(stars or 0)) + 1) / 5.0)


def license_trust(license_name: str) -> float:
    name = (license_name or "").lower()
    if any(x in name for x in ("mit", "apache", "bsd", "isc", "unlicense", "mpl")):
        return 1.0
    if "gpl" in name or "lgpl" in name:
        return 0.7
    if not name or name in ("noassertion", "none"):
        return 0.25
    return 0.55


def parse_frontmatter(text: str) -> dict:
    if not text or not text.lstrip().startswith("---"):
        return {}
    stripped = text.lstrip("\ufeff \r\n")
    end = stripped.find("\n---", 3)
    if end < 0:
        return {}
    block = stripped[3:end].strip("\r\n")
    data: dict[str, str] = {}
    current = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if current and line[:1].isspace():
            data[current] += " " + line.strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in ("|", ">"):
            value = ""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key] = value
        current = key
    return data


def risk_scan(text: str) -> list[str]:
    found = []
    for pattern, label in RISK_PATTERNS:
        if pattern.search(text or ""):
            found.append(label)
    return found


# --------------------------------------------------------------------------- #
# proxy / http
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {}


def tcp_ok(proxy: str, timeout: float = 1.2) -> bool:
    try:
        p = urllib.parse.urlparse(proxy if "://" in proxy else "http://" + proxy)
        with socket.create_connection((p.hostname, p.port or 80), timeout=timeout):
            return True
    except Exception:
        return False


def resolve_proxy(explicit: str | None, no_proxy: bool) -> str | None:
    if no_proxy:
        return None
    if explicit:
        return explicit if "://" in explicit else "http://" + explicit
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            return value if "://" in value else "http://" + value
    configured = load_config().get("proxy")
    if configured and tcp_ok(configured):
        return configured
    return None


def find_token(no_token: bool = False) -> tuple[str | None, str]:
    if no_token:
        return None, "disabled"
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value.strip(), f"env:{key}"
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() in ("GITHUB_TOKEN", "GH_TOKEN"):
                    return value.strip().strip("\"'"), "env-file"
        except Exception:
            pass
    candidates = [
        shutil.which("git-credential-manager"),
        r"D:\Git\mingw64\bin\git-credential-manager.exe",
        r"C:\Program Files\Git\mingw64\bin\git-credential-manager.exe",
    ]
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        try:
            proc = subprocess.run(
                [path, "get"],
                input="protocol=https\nhost=github.com\n\n",
                text=True, capture_output=True, timeout=20,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1].strip(), "git-credential-manager"
        except Exception:
            continue
    return None, "none"


class HttpClient:
    def __init__(self, proxy: str | None, timeout: int = 25):
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
        self.timeout = timeout
        self.opener = urllib.request.build_opener(*handlers)
        self.cache: dict[str, str] = {}
        self.calls = 0

    def text(self, url: str, headers: dict | None = None, retries: int = 2) -> str:
        if url in self.cache:
            return self.cache[url]
        request_headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"}
        if headers:
            request_headers.update(headers)
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                self.calls += 1
                req = urllib.request.Request(url, headers=request_headers)
                with self.opener.open(req, timeout=self.timeout) as resp:
                    data = resp.read()
                text = data.decode("utf-8", errors="replace")
                self.cache[url] = text
                return text
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 403) and attempt < retries:
                    retry = exc.headers.get("Retry-After")
                    time.sleep(min(float(retry) if retry and retry.isdigit() else 1.5, 4.0))
                    continue
                if exc.code >= 500 and attempt < retries:
                    time.sleep(1.0)
                    continue
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                raise ScoutError(f"HTTP {exc.code} for {url}: {detail}") from exc
            except Exception as exc:
                last = exc
                if attempt < retries:
                    time.sleep(1.0)
                    continue
        raise ScoutError(f"request failed: {url}: {last}")


class GitHub:
    def __init__(self, http: HttpClient, token: str | None):
        self.http = http
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.rate: dict[str, str] = {}

    def _json(self, url: str) -> dict:
        text = self.http.text(url, self.headers)
        try:
            return json.loads(text)
        except Exception as exc:
            raise ScoutError(f"invalid GitHub JSON from {url}") from exc

    def search_repos(self, query: str, per_page: int = 10) -> list[dict]:
        url = (
            "https://api.github.com/search/repositories?q="
            + urllib.parse.quote(query)
            + f"&sort=stars&order=desc&per_page={per_page}"
        )
        data = self._json(url)
        return data.get("items", []) or []

    def search_code(self, query: str, per_page: int = 10) -> list[dict]:
        if not self.token:
            return []
        url = (
            "https://api.github.com/search/code?q="
            + urllib.parse.quote(query)
            + f"&per_page={per_page}"
        )
        try:
            data = self._json(url)
        except ScoutError:
            return []
        return data.get("items", []) or []

    def repo(self, full_name: str) -> dict:
        return self._json(f"https://api.github.com/repos/{full_name}")

    def tree(self, full_name: str) -> list[dict]:
        try:
            data = self._json(f"https://api.github.com/repos/{full_name}/git/trees/HEAD?recursive=1")
            return data.get("tree", []) or []
        except ScoutError:
            return []

    def raw(self, full_name: str, path: str) -> str:
        url = f"https://raw.githubusercontent.com/{full_name}/HEAD/{urllib.parse.quote(path)}"
        return self.http.text(url, {"Accept": "text/plain"})
# --------------------------------------------------------------------------- #
# local skills
# --------------------------------------------------------------------------- #

def local_skill_dirs() -> list[Path]:
    dirs = [ROOT / ".dsh" / "skills", DSH_HOME / "skills", Path.home() / ".agents" / "skills"]
    bundled = os.environ.get("DSH_BUNDLED_SKILL_DIR")
    if bundled:
        dirs.append(Path(bundled))
    for item in load_config().get("bundledSkillDirs") or []:
        dirs.append(Path(str(item)).expanduser())
    # Common install locations for the shipped office skills. Missing paths
    # are harmless; the list is filtered below.
    dirs += [
        Path(r"D:\deepseekharness\resources\runtime\office-skills"),
        Path(r"C:\Program Files\DeepSeek Harness\resources\runtime\office-skills"),
        Path.home() / "AppData" / "Local" / "Programs" / "DeepSeek Harness" / "resources" / "runtime" / "office-skills",
    ]
    seen: set[str] = set()
    out: list[Path] = []
    for directory in dirs:
        key = str(directory).lower()
        if key not in seen and directory.exists():
            seen.add(key)
            out.append(directory)
    return out


def local_relevance(terms: list[str], *texts: str) -> float:
    if not terms:
        return 0.0
    blob = normalize(" ".join(texts))
    hits = sum(1 for term in terms if term_in(term, blob))
    return min(1.0, hits / max(2, min(len(terms), 4)))


def load_local_skills(terms: list[str], profile: dict | None = None) -> list[Candidate]:
    found: list[Candidate] = []
    seen: set[str] = set()
    for directory in local_skill_dirs():
        for path in sorted(directory.glob("*/SKILL.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta = parse_frontmatter(text)
            name = meta.get("name") or path.parent.name
            if profile and name.lower() == "download" and not any(a in (profile.get("actions") or []) for a in ("download", "save", "fetch")):
                continue
            if profile and name.lower() == "scout" and not any(
                t in (profile.get("terms") or []) for t in ("skill", "skills", "plugin", "plugins", "recommend", "suggest")
            ):
                continue
            if name in seen:
                continue
            seen.add(name)
            description = meta.get("description") or ""
            when = meta.get("whenToUse") or ""
            rel = local_relevance(terms, name, description, when) if terms else 0.5
            if terms and any(t in normalize(name) for t in terms):
                rel = min(1.0, rel + 0.2)
            if terms and rel < 0.1:
                continue
            candidate = Candidate(
                kind="local",
                name=name,
                url=str(path),
                description=description,
                path=str(path),
                source="local",
                install="已安装",
                relevance=rel,
                installed=True,
                verified=True,
                reasons=[f"本地已安装", f"相关度 {rel:.0%}"],
                tags=["local"],
                extra={"dir": str(path.parent)},
            )
            candidate.compatibility = 1.0
            candidate.trust = 1.0
            candidate.freshness = 1.0
            candidate.popularity = 0.0
            candidate.score = 0.70 * rel + 0.25
            found.append(candidate)
    found.sort(key=lambda c: c.score, reverse=True)
    return found


# --------------------------------------------------------------------------- #
# skills
# --------------------------------------------------------------------------- #

def choose_skill_path(paths: list[str], terms: list[str]) -> list[str]:
    def score(path: str) -> float:
        low = path.lower()
        value = 0.0
        if low == "skill.md":
            value += 1.0
        if low.endswith("/skill.md"):
            value += 0.2
        if "template" in low or "example" in low:
            value -= 0.6
        if "skill" in low:
            value += 0.1
        value += relevance(terms, path)
        return value

    ranked = sorted(paths, key=score, reverse=True)
    return ranked[:2]


def evaluate_skill_repo(
    repo: dict,
    gh: GitHub,
    terms: list[str],
    profile: dict,
    known_paths: list[str] | None = None,
    max_skills: int = 2,
    allow_body_match: bool = False,
) -> list[Candidate]:
    full_name = repo.get("full_name") or ""
    if not full_name or repo.get("archived"):
        return []
    size = int(repo.get("size") or 0)
    if size > 300_000 and not known_paths:
        return []
    owner = (repo.get("owner") or {}).get("login") or full_name.split("/")[0]
    license_name = ((repo.get("license") or {}).get("spdx_id") or "").strip()
    description = repo.get("description") or ""
    topics = repo.get("topics") or []
    pushed = repo.get("pushed_at") or repo.get("updated_at") or ""
    stars = int(repo.get("stargazers_count") or 0)
    html_url = repo.get("html_url") or f"https://github.com/{full_name}"

    paths = known_paths or []
    if not paths:
        tree = gh.tree(full_name)
        paths = [
            item["path"] for item in tree
            if item.get("type") == "blob"
            and (item.get("path", "").lower() == "skill.md" or item.get("path", "").lower().endswith("/skill.md"))
        ]
    if not paths:
        rel = relevance(terms, full_name, description, " ".join(topics))
        if rel < 0.35 or not has_strong_match(profile, full_name, description, " ".join(topics)):
            return []
        candidate = Candidate(
            kind="skill",
            name=full_name.split("/")[-1],
            url=html_url,
            description=description,
            stars=stars,
            pushed_at=pushed,
            license=license_name,
            owner=owner,
            source="github",
            relevance=rel,
            verified=False,
            reasons=[f"仓库与目标相关（{rel:.0%}）"],
            risks=["未找到 SKILL.md，可能只是工具/列表而不是技能"],
            tags=topics[:6],
        )
        candidate.compatibility = 0.25
        candidate.trust = license_trust(license_name)
        candidate.freshness = freshness(pushed)
        candidate.popularity = popularity(stars)
        candidate.score = (
            0.50 * rel + 0.20 * candidate.popularity + 0.12 * candidate.freshness
            + 0.10 * candidate.compatibility + 0.08 * candidate.trust
        )
        return [candidate]

    selected = choose_skill_path(paths, terms)
    candidates: list[Candidate] = []
    for path in selected[:max_skills]:
        try:
            text = gh.raw(full_name, path)
        except ScoutError:
            continue
        meta = parse_frontmatter(text)
        name = meta.get("name") or Path(path).parent.name or full_name.split("/")[-1]
        desc = meta.get("description") or description
        when = meta.get("whenToUse") or ""
        match_text = (name, desc, when, text[:3000]) if allow_body_match else (name, desc, when)
        if not has_strong_match(profile, *match_text):
            continue
        rel = relevance(terms, name, desc, when, path, " ".join(topics), text[:6000])
        if rel < 0.12:
            continue
        risks = risk_scan(text)
        if not license_name:
            risks.append("仓库未声明 license，使用/分发前需确认")
        if not meta:
            risks.append("SKILL.md frontmatter 不完整")
        compat = 0.45
        if meta.get("name") and meta.get("description"):
            compat += 0.25
        if license_name:
            compat += 0.15
        if len(text) > 400:
            compat += 0.15
        compat = min(1.0, compat)
        trust = license_trust(license_name)
        owner_type = ((repo.get("owner") or {}).get("type") or "").lower()
        if owner_type == "organization":
            trust = min(1.0, trust + 0.05)
        cand = Candidate(
            kind="skill",
            name=str(name),
            url=html_url,
            description=str(desc),
            stars=stars,
            pushed_at=pushed,
            license=license_name or "未声明",
            owner=owner,
            path=path,
            source="github",
            install=f"复制 {full_name}/{path} 到 .dsh/skills/{name}",
            relevance=rel,
            compatibility=compat,
            trust=trust,
            freshness=freshness(pushed),
            popularity=popularity(stars),
            verified=bool(meta.get("name") and meta.get("description")),
            reasons=[],
            risks=risks,
            tags=topics[:6],
            extra={"repo": full_name, "skill_path": path},
        )
        matched = [t for t in terms if t in normalize(f"{name} {desc} {when} {text[:4000]}")][:5]
        if profile.get("entity_terms") and any(e in normalize(f"{name} {desc} {when}") for e in profile["entity_terms"]):
            cand.relevance = min(1.0, cand.relevance + 0.08)
            cand.reasons.append("平台匹配：" + "、".join(profile.get("entities") or []))
        if matched:
            cand.reasons.append("命中关键词：" + "、".join(matched))
        if stars >= 1000:
            cand.reasons.append(f"社区认可度高（{stars:,} stars）")
        if cand.freshness >= 0.8:
            cand.reasons.append("近期仍在更新")
        if cand.verified:
            cand.reasons.append("SKILL.md 结构完整")
        cand.score = (
            0.50 * rel + 0.20 * cand.popularity + 0.12 * cand.freshness
            + 0.10 * compat + 0.08 * trust
        )
        if risks:
            cand.score *= 0.92
        candidates.append(cand)
    return candidates


def english_terms(terms: list[str]) -> list[str]:
    return [t for t in terms if re.search(r"[a-zA-Z]", t)][:6]


def query_terms(terms: list[str]) -> str:
    english = english_terms(terms)
    if english:
        return " ".join(english[:4])
    chinese = [t for t in terms if re.search(r"[\u4e00-\u9fff]", t)]
    return " ".join(chinese[:3])


def search_skills(terms: list[str], gh: GitHub, token: str | None, warnings: list[str], profile: dict) -> tuple[list[Candidate], list[str]]:
    queries: list[str] = []
    core = query_terms(terms)
    if core:
        queries += [
            f'{core} skill in:name,description,readme',
            f'{core} topic:claude-skills',
            f'{core} topic:agent-skills',
            f'{core} "SKILL.md" in:readme',
        ]
    else:
        queries.append(f'{core or "agent skill"} skill')
    repos: dict[str, dict] = {}
    for query in queries:
        try:
            for repo in gh.search_repos(query, per_page=10):
                full = repo.get("full_name")
                if full and full not in repos:
                    repos[full] = repo
        except ScoutError as exc:
            warnings.append(f"GitHub 搜索失败：{exc}")
    ranked = sorted(repos.values(), key=lambda r: int(r.get("stargazers_count") or 0), reverse=True)
    candidates: list[Candidate] = []
    for repo in ranked[:MAX_REPOS]:
        try:
            candidates.extend(evaluate_skill_repo(repo, gh, terms, profile))
        except ScoutError as exc:
            warnings.append(f"读取 {repo.get('full_name')} 失败：{exc}")

    # Code search finds small but exact skills that repository search misses.
    if token and core:
        code_query = query_terms(terms)
        queries.append(f"code:filename:SKILL.md {code_query}")
        try:
            items = gh.search_code(f"filename:SKILL.md {code_query}", per_page=MAX_CODE_RESULTS)
        except ScoutError:
            items = []
        if not items:
            warnings.append("GitHub 代码搜索未返回结果（可能触发 10 次/分钟限流）")
        seen_repos = {c.extra.get("repo") for c in candidates}
        for item in items[:MAX_CODE_RESULTS]:
            repo_info = item.get("repository") or {}
            full = repo_info.get("full_name")
            if not full or full in seen_repos:
                continue
            try:
                repo = gh.repo(full)
            except ScoutError:
                continue
            seen_repos.add(full)
            candidates.extend(evaluate_skill_repo(
                repo, gh, terms, profile, known_paths=[item.get("path")],
                max_skills=1, allow_body_match=True,
            ))
            if len(candidates) >= 16:
                break

    # De-duplicate by repo + path, keeping the better score.
    best: dict[tuple[str, str], Candidate] = {}
    for cand in candidates:
        key = (cand.extra.get("repo") or cand.url, cand.path or cand.name)
        if key not in best or cand.score > best[key].score:
            best[key] = cand
    result = sorted(best.values(), key=lambda c: c.score, reverse=True)
    return result, queries

# --------------------------------------------------------------------------- #
# plugins
# --------------------------------------------------------------------------- #

def load_plugin_registry(http: HttpClient, refresh: bool, warnings: list[str]) -> tuple[list[dict], str]:
    PLUGIN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if PLUGIN_CACHE.exists() and not refresh:
        age = time.time() - PLUGIN_CACHE.stat().st_mtime
        if age < PLUGIN_TTL:
            try:
                data = json.loads(PLUGIN_CACHE.read_text(encoding="utf-8"))
                return data.get("plugins", []), "cache"
            except Exception:
                pass
    try:
        text = http.text(PLUGIN_REGISTRY_URL, {"Accept": "application/json"})
        data = json.loads(text)
        plugins = data.get("plugins", []) or []
        if not plugins:
            raise ScoutError("plugin registry is empty")
        tmp = PLUGIN_CACHE.with_name(PLUGIN_CACHE.name + ".tmp")
        tmp.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "count": len(plugins), "plugins": plugins}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PLUGIN_CACHE)
        return plugins, "live"
    except Exception as exc:
        if PLUGIN_CACHE.exists():
            warnings.append(f"插件目录刷新失败，使用旧缓存：{exc}")
            try:
                data = json.loads(PLUGIN_CACHE.read_text(encoding="utf-8"))
                return data.get("plugins", []), "stale-cache"
            except Exception:
                pass
        warnings.append(f"插件目录不可用：{exc}")
        return [], "unavailable"


def installed_plugin_names() -> set[str]:
    names: set[str] = set()
    for path in DSH_HOME.glob("profiles/*/cordis.patch.yml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.findall(r'name:\s*["\']?(@deepseek-ai/dsh-[a-z0-9-]+)', text):
            names.add(match)
    return names


def plugin_candidate(entry: dict, terms: list[str], goal: str, profile: dict) -> Candidate | None:
    name = entry.get("name") or ""
    if not name:
        return None
    raw_desc = entry.get("description")
    if isinstance(raw_desc, dict):
        en = raw_desc.get("en") or ""
        zh = raw_desc.get("zh") or ""
    else:
        en = str(raw_desc or "")
        zh = en
    category = entry.get("category") or ""
    caps = entry.get("capabilities") or []
    if not has_strong_match(profile, name, en, zh, category, " ".join(caps)):
        return None
    rel = relevance(terms, name, en, zh, category, " ".join(caps))
    if rel < 0.06:
        return None
    stars = int(entry.get("stars") or 0)
    added = entry.get("added") or ""
    install = entry.get("install") or f"dsh plugin --profile web add {entry.get('url') or name}"
    risks: list[str] = []
    risky_caps = [c for c in caps if c in ("shell", "fs-write", "network", "env", "subagent")]
    if risky_caps:
        risks.append("需要权限：" + "、".join(risky_caps))
    if entry.get("capabilityRedLines"):
        risks.append("目录标记了红线能力：" + "、".join(entry["capabilityRedLines"][:5]))
    if not entry.get("npm") and not entry.get("version"):
        risks.append("未发布 npm 版本，安装前需审查源码")
    description = zh if re.search(r"[\u4e00-\u9fff]", goal) and zh else en or zh
    compat = 0.5
    if entry.get("npm") or entry.get("version"):
        compat += 0.2
    if install:
        compat += 0.15
    if entry.get("url"):
        compat += 0.15
    trust = 0.55
    if stars >= 10:
        trust += 0.1
    if entry.get("capabilityCheckedAt"):
        trust += 0.1
    if entry.get("capabilityRedLines"):
        trust -= 0.2
    trust = max(0.0, min(1.0, trust))
    cand = Candidate(
        kind="plugin",
        name=name,
        url=entry.get("page") or entry.get("url") or "",
        description=description,
        stars=stars,
        pushed_at=added,
        license="见仓库",
        owner=entry.get("owner") or "",
        source="awesome-dsh-plugin",
        install=install,
        relevance=rel,
        compatibility=min(1.0, compat),
        trust=trust,
        freshness=freshness(added),
        popularity=popularity(stars),
        verified=True,
        risks=risks,
        tags=[category] + list(caps),
        extra={
            "npm": entry.get("npm"),
            "version": entry.get("version"),
            "capabilities": caps,
            "category": category,
        },
    )
    matched = [t for t in terms if t in normalize(f"{name} {en} {zh} {category}")][:5]
    if profile.get("entity_terms") and any(e in normalize(f"{name} {en} {zh} {category}") for e in profile["entity_terms"]):
        cand.relevance = min(1.0, cand.relevance + 0.10)
        cand.reasons.append("平台匹配：" + "、".join(profile.get("entities") or []))
    if matched:
        cand.reasons.append("命中关键词：" + "、".join(matched))
    if stars:
        cand.reasons.append(f"{stars:,} stars")
    if category:
        cand.reasons.append(f"分类：{category}")
    if entry.get("capabilityCheckedAt"):
        cand.reasons.append("有权限能力标注")
    cand.score = (
        0.50 * rel + 0.20 * cand.popularity + 0.12 * cand.freshness
        + 0.10 * cand.compatibility + 0.08 * cand.trust
    )
    if risks:
        cand.score *= 0.94
    return cand


def npm_search(http: HttpClient, query: str, terms: list[str], goal: str, profile: dict, kind: str = "plugin") -> list[Candidate]:
    url = "https://registry.npmjs.org/-/v1/search?text=" + urllib.parse.quote(query) + "&size=20"
    try:
        data = json.loads(http.text(url, {"Accept": "application/json"}))
    except Exception:
        return []
    out: list[Candidate] = []
    for obj in data.get("objects", []):
        pkg = obj.get("package") or {}
        name = pkg.get("name") or ""
        desc = pkg.get("description") or ""
        blob = normalize(f"{name} {desc} {' '.join(pkg.get('keywords') or [])}")
        if kind == "plugin" and not any(h in blob for h in PLUGIN_HINTS):
            continue
        if kind == "mcp" and "mcp" not in blob and "model context protocol" not in blob:
            continue
        if not has_strong_match(profile, name, desc, " ".join(pkg.get("keywords") or [])):
            continue
        rel = relevance(terms, name, desc, " ".join(pkg.get("keywords") or []))
        if rel < 0.08:
            continue
        date = (pkg.get("date") or "")[:10]
        cand = Candidate(
            kind=kind,
            name=name,
            url=(pkg.get("links") or {}).get("npm") or f"https://www.npmjs.com/package/{name}",
            description=desc,
            stars=0,
            pushed_at=date,
            license="见 npm",
            owner=(pkg.get("publisher") or {}).get("username") or "",
            source="npm",
            install=(f"dsh plugin --profile web add {name}" if kind == "plugin" else f"npx -y {name}"),
            relevance=rel,
            freshness=freshness(date),
            popularity=0.15,
            verified=True,
            risks=["第三方 npm 包；安装前检查源码与 install 脚本"] if kind == "plugin" else ["MCP server；需加入 DSH MCP 配置并限制凭据"],
            tags=["npm", kind],
            extra={"version": pkg.get("version"), "publisher": (pkg.get("publisher") or {}).get("username")},
        )
        cand.compatibility = 0.55
        cand.trust = 0.45
        cand.reasons = [f"npm 包 {pkg.get('version') or ''}", "关键词相关"]
        cand.score = (0.50 * rel + 0.20 * cand.popularity + 0.12 * cand.freshness
                      + 0.10 * cand.compatibility + 0.08 * cand.trust)
        if kind == "mcp":
            cand.score = min(1.0, cand.score + 0.15)
            cand.reasons.append("MCP server")
        out.append(cand)
    return out


def search_plugins(goal: str, terms: list[str], http: HttpClient, refresh: bool, warnings: list[str], profile: dict, limit: int = 5) -> tuple[list[Candidate], list[str]]:
    plugins, source = load_plugin_registry(http, refresh, warnings)
    installed = installed_plugin_names()
    candidates: list[Candidate] = []
    for entry in plugins:
        cand = plugin_candidate(entry, terms, goal, profile)
        if cand:
            if cand.name in installed or cand.extra.get("npm") in installed:
                cand.installed = True
            candidates.append(cand)
    candidates.sort(key=lambda c: c.score, reverse=True)
    core = " ".join(english_terms(terms)[:4])
    queries = [f"registry:{PLUGIN_REGISTRY_URL} ({len(plugins)} entries, {source})"]
    if core:
        for q in (f"{core} dsh-plugin", f"{core} deepseek harness plugin"):
            queries.append(f"npm:{q}")
            for cand in npm_search(http, q, terms, goal, profile):
                if not any(c.name == cand.name for c in candidates):
                    candidates.append(cand)
    if re.search(r"\bmcp\b|model context protocol", normalize(goal)):
        q = f"mcp {core}".strip()
        queries.append(f"npm:{q}")
        for cand in npm_search(http, q, terms, goal, profile, kind="mcp"):
            if not any(c.name == cand.name for c in candidates):
                candidates.append(cand)
    # Keep a stable order after adding npm/MCP supplements.
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit], queries

# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def cache_key(goal: str, limit: int) -> str:
    return hashlib.sha1(f"{CACHE_SCHEMA}|{goal.strip().lower()}|{limit}".encode("utf-8")).hexdigest()


def load_cache(key: str, ttl: int = CACHE_TTL) -> dict | None:
    if not CACHE.exists():
        return None
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        entry = (data.get("entries") or {}).get(key)
        if entry and time.time() - float(entry.get("ts") or 0) < ttl:
            result = entry.get("result")
            if isinstance(result, dict):
                result["cached"] = True
                return result
    except Exception:
        pass
    return None


def save_cache(key: str, result: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    data = {"entries": {}}
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            if not isinstance(data.get("entries"), dict):
                data = {"entries": {}}
        except Exception:
            data = {"entries": {}}
    data["entries"][key] = {"ts": time.time(), "result": result}
    # Keep the cache bounded.
    if len(data["entries"]) > 50:
        items = sorted(data["entries"].items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:50]
        data["entries"] = dict(items)
    tmp = CACHE.with_name(CACHE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE)


def advise(
    goal: str,
    limit: int = 5,
    refresh: bool = False,
    proxy: str | None = None,
    no_proxy: bool = False,
    no_token: bool = False,
    debug: bool = False,
) -> dict:
    goal = (goal or "").strip()
    if len(goal) < 2:
        raise ScoutError("请描述你要做的项目、功能或目的（至少 2 个字符）")
    limit = max(1, min(10, int(limit or 5)))
    key = cache_key(goal, limit) + ("-anon" if no_token else "")
    if not refresh:
        cached = load_cache(key)
        if cached:
            return cached

    started = time.time()
    profile = goal_profile(goal)
    terms = profile["terms"]
    token, token_source = find_token(no_token)
    resolved_proxy = resolve_proxy(proxy, no_proxy)
    http = HttpClient(resolved_proxy, timeout=55)
    gh = GitHub(http, token)
    warnings: list[str] = []
    if not token:
        warnings.append("没有 GitHub token，搜索使用匿名限额；结果可能较少。")
    local = load_local_skills(terms, profile)
    skills, queries = search_skills(terms, gh, token, warnings, profile)
    plugins, plugin_queries = search_plugins(goal, terms, http, refresh, warnings, profile, limit=limit)

    local_names = {c.name.lower() for c in local}
    skills = [c for c in skills if c.name.lower() not in local_names]
    skills.sort(key=lambda c: c.score, reverse=True)
    skills = skills[:limit]
    for c in local:
        c.score = round(c.score, 3)

    result = {
        "goal": goal,
        "terms": terms,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "token_source": token_source,
        "proxy": resolved_proxy or "direct",
        "queries": queries + plugin_queries,
        "local": [c.as_dict() for c in local[:limit]],
        "skills": [c.as_dict() for c in skills],
        "plugins": [c.as_dict() for c in plugins],
        "warnings": warnings,
        "stats": {
            "local": len(local),
            "skills": len(skills),
            "plugins": len(plugins),
            "api_calls": http.calls,
            "seconds": round(time.time() - started, 1),
        },
        "suggest_generate": not skills and not plugins,
        "cached": False,
    }
    if debug:
        print(
            f"[scout] terms={terms} calls={http.calls} seconds={result['stats']['seconds']} "
            f"token={token_source} proxy={resolved_proxy or 'direct'}",
            file=sys.stderr,
        )
    save_cache(key, result)
    return result


def stars_text(stars: int) -> str:
    if not stars:
        return "—"
    if stars >= 1000:
        return f"{stars / 1000:.1f}k"
    return str(stars)


def render_candidate(cand: dict, index: int) -> list[str]:
    lines = []
    name = cand.get("name") or "未命名"
    score = float(cand.get("score") or 0)
    kind = cand.get("kind")
    lines.append(f"### {index}. {name}  ·  {score * 100:.0f} 分")
    lines.append("")
    lines.append(f"- 来源：[{cand.get('source') or kind}]({cand.get('url') or '#'})")
    bits = []
    if cand.get("stars"):
        bits.append(f"★ {stars_text(cand['stars'])}")
    if cand.get("pushed_at"):
        bits.append(f"更新 {cand['pushed_at'][:10]}")
    if cand.get("license"):
        bits.append(f"License {cand['license']}")
    if cand.get("kind") == "plugin" and cand.get("extra", {}).get("version"):
        bits.append(f"v{cand['extra']['version']}")
    if bits:
        lines.append("- " + " · ".join(bits))
    if cand.get("path") and cand.get("kind") == "skill":
        lines.append(f"- SKILL.md：`{cand['path']}`")
    if cand.get("description"):
        desc = re.sub(r"\s+", " ", cand["description"]).strip()
        lines.append(f"- 说明：{desc[:300]}")
    reasons = cand.get("reasons") or []
    if reasons:
        lines.append("- 为什么：" + "；".join(reasons[:4]))
    risks = cand.get("risks") or []
    if risks:
        lines.append("- 风险：" + "；".join(risks[:5]))
    if cand.get("install"):
        lines.append(f"- 安装/使用：`{cand['install']}`")
    lines.append("")
    return lines


def render_markdown(result: dict) -> str:
    lines = [
        "# Scout 侦察报告",
        "",
        f"**目标：** {result.get('goal', '')}",
        "",
        f"**时间：** {result.get('generated_at', '')}  ·  "
        f"**Token：** {result.get('token_source', 'none')}  ·  "
        f"**代理：** {result.get('proxy', 'direct')}",
        "",
    ]
    stats = result.get("stats") or {}
    lines.append(
        f"扫描到 **{stats.get('local', 0)}** 个本地技能、"
        f"**{stats.get('skills', 0)}** 个 GitHub skill、"
        f"**{stats.get('plugins', 0)}** 个插件候选；"
        f"API 调用 {stats.get('api_calls', 0)} 次，用时 {stats.get('seconds', 0)} 秒。"
    )
    if result.get("cached"):
        lines.append("\n> 这是缓存结果；加 `--refresh` 可重新搜索。")
    lines.append("")

    local = result.get("local") or []
    if local:
        lines += ["## 本地已有（优先复用）", ""]
        for i, cand in enumerate(local, 1):
            lines += render_candidate(cand, i)

    skills = result.get("skills") or []
    lines += ["## GitHub Skills", ""]
    if skills:
        for i, cand in enumerate(skills, 1):
            lines += render_candidate(cand, i)
    else:
        lines += ["没有找到足够匹配的 GitHub skill。", ""]

    plugins = result.get("plugins") or []
    lines += ["## 插件 / MCP", ""]
    if plugins:
        for i, cand in enumerate(plugins, 1):
            lines += render_candidate(cand, i)
    else:
        lines += ["没有找到匹配的插件；可以改为生成一个项目内 skill。", ""]

    warnings = result.get("warnings") or []
    if warnings:
        lines += ["## 警告", ""]
        lines += [f"- {w}" for w in warnings]
        lines.append("")

    lines += ["## 下一步", ""]
    if result.get("suggest_generate"):
        lines += [
            "没有找到合适的现成结果。v2.2 会提供 `scout new skill` 生成器；"
            "当前可以先描述具体输入/输出，再手写一个最小 skill。",
        ]
    else:
        lines += [
            "1. 先看「本地已有」，能复用就不要重复安装。",
            "2. 选中 GitHub skill 后，先读 `SKILL.md` 与 `scripts/`，再复制到 `.dsh/skills/<name>/`。",
            "3. 插件必须审查能力标注（shell / fs-write / network），确认后再安装；v2.1 才提供自动安装。",
        ]
    lines.append("")
    lines.append("---")
    lines.append("来源：GitHub 仓库搜索、SKILL.md 原文、awesome-dsh-plugin 目录、npm registry。")
    return "\n".join(lines)


def save_report(result: dict, markdown: str) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = REPORTS / f"scout-{stamp}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    md_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_doctor(args: argparse.Namespace) -> int:
    token, source = find_token(args.no_token)
    proxy = resolve_proxy(args.proxy, args.no_proxy)
    print(f"root        {ROOT}")
    print(f"token       {source}")
    print(f"proxy       {proxy or 'direct'}")
    local = load_local_skills([])
    print(f"local       {len(local)} skill(s)")
    if PLUGIN_CACHE.exists():
        age = time.time() - PLUGIN_CACHE.stat().st_mtime
        try:
            data = json.loads(PLUGIN_CACHE.read_text(encoding="utf-8"))
            count = data.get("count") or len(data.get("plugins", []))
            print(f"plugin db   {count} entries, {age / 3600:.1f}h old")
        except Exception:
            print("plugin db   unreadable")
    else:
        print("plugin db   not cached (first advise downloads ~10 MB)")
    print(f"cache       {'present' if CACHE.exists() else 'empty'}")
    return 0


def run_cli(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        return cmd_doctor(args)
    goal = " ".join(args.goal).strip()
    try:
        result = advise(
            goal,
            limit=args.limit,
            refresh=args.refresh,
            proxy=args.proxy,
            no_proxy=args.no_proxy,
            no_token=args.no_token,
            debug=args.debug,
        )
    except ScoutError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    if args.command == "skills":
        result["plugins"] = []
    elif args.command == "plugins":
        result["skills"] = []
        result["local"] = []
    if args.save:
        md = render_markdown(result)
        md_path, json_path = save_report(result, md)
        print(f"[saved] {md_path}", file=sys.stderr)
        print(f"[saved] {json_path}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scout", description="Recommend Agent Skills and DSH plugins for a goal.")
    parser.add_argument("--version", action="version", version="FetchDesk Scout 2.0")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("goal", nargs="+", help="what the project should do")
        p.add_argument("--limit", type=int, default=5, help="results per section (1-10)")
        p.add_argument("--refresh", action="store_true", help="ignore the 24h cache")
        p.add_argument("--json", action="store_true", help="print JSON only")
        p.add_argument("--save", action="store_true", help="write reports/scout-*.md and .json")
        p.add_argument("--no-token", action="store_true", help="do not use a GitHub token")
        p.add_argument("--proxy", help="proxy URL")
        p.add_argument("--no-proxy", action="store_true", help="connect directly")
        p.add_argument("--debug", action="store_true")

    p_advise = sub.add_parser("advise", help="recommend skills and plugins")
    common(p_advise)
    p_skills = sub.add_parser("skills", help="recommend skills only")
    common(p_skills)
    p_plugins = sub.add_parser("plugins", help="recommend plugins/MCP only")
    common(p_plugins)
    p_doc = sub.add_parser("doctor", help="check token, proxy, caches")
    p_doc.add_argument("--no-token", action="store_true")
    p_doc.add_argument("--proxy")
    p_doc.add_argument("--no-proxy", action="store_true")
    p_doc.set_defaults(command="doctor")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["--help"]
    elif argv[0] not in ("advise", "skills", "plugins", "doctor") and not argv[0].startswith("-"):
        argv.insert(0, "advise")
    args = build_parser().parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
