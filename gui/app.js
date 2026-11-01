/* FetchDesk UI — plain JS, no build step. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  const state = {
    view: "download",
    mode: "auto",
    status: null,
    jobs: [],
    history: [],
    busy: false,
    polling: false,
    settingsFilled: false,
    lastStatusAt: 0,
  };

  const MODE = {
    auto: { label: "自动", icon: "i-download" },
    video: { label: "视频", icon: "i-film" },
    audio: { label: "音频", icon: "i-music" },
    images: { label: "图片", icon: "i-image" },
    file: { label: "文件", icon: "i-file" },
    article: { label: "文章", icon: "i-article" },
    torrent: { label: "种子", icon: "i-magnet" },
  };
  const STATUS_LABEL = { queued: "排队中", running: "下载中", done: "完成", error: "失败", cancelled: "已取消" };
  const PHASE_LABEL = {
    queued: "排队中", file: "下载文件", video: "下载视频", audio: "提取音频",
    images: "抓取图集", article: "提取正文", torrent: "连接种子",
    download: "下载中", done: "完成",
  };
  function phaseText(value) {
    return PHASE_LABEL[value] || value || "";
  }

  let apiReady = false;
  let pollTimer = null;
  let toastTimer = null;

  const TOKEN = new URLSearchParams(location.search).get("token") || "";

  async function api(method, ...args) {
    const response = await fetch("/api/" + method, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-FetchDesk-Token": TOKEN },
      body: JSON.stringify({ args }),
    });
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) throw new Error((data && data.error) || ("HTTP " + response.status));
    return data;
  }

  function toast(message, type = "") {
    const el = $("#toast");
    el.textContent = message;
    el.className = "toast show " + type;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = "toast " + type; }, 3600);
  }

  function humanBytes(value) {
    let n = Number(value || 0);
    if (!isFinite(n) || n <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? Math.round(n) : n.toFixed(1)) + " " + units[i];
  }

  function clock(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    if (s < 60) return s + " 秒";
    const m = Math.floor(s / 60);
    if (m < 60) return m + " 分 " + (s % 60) + " 秒";
    return Math.floor(m / 60) + " 小时 " + (m % 60) + " 分";
  }

  function shortDate(value) {
    if (!value) return "";
    const d = new Date(value);
    if (isNaN(d.getTime())) return String(value).slice(0, 16);
    return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url || "链接"; }
  }

  function fileName(path) {
    return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "文件";
  }

  function jobTitle(job) {
    if (job.title) return job.title;
    if (job.files && job.files.length) return fileName(job.files[0]);
    return hostOf(job.url);
  }

  function modeOf(job) {
    return MODE[job.mode] || MODE.auto;
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    if (apiReady) return;
    apiReady = true;
    applyTheme(localStorage.getItem("fetchdesk-theme") || "dark");
    bind();
    refreshStatus();
    refreshJobs().then(refreshHistory);
    schedulePoll(600);
  }

  function schedulePoll(delay) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      if (!apiReady) return;
      try {
        await refreshJobs();
        if (Date.now() - state.lastStatusAt > 25000) await refreshStatus();
      } catch (err) {
        console.warn(err);
      }
      const active = state.jobs.some((j) => j.status === "running" || j.status === "queued");
      schedulePoll(active ? 750 : 2600);
    }, delay);
  }

  // ------------------------------------------------------------------ data
  async function refreshStatus() {
    try {
      const status = await api("status");
      state.status = status;
      state.lastStatusAt = Date.now();
      renderStatus();
      if (!state.settingsFilled) { fillSettings(status); state.settingsFilled = true; }
    } catch (err) {
      console.warn("status", err);
    }
  }

  async function refreshJobs() {
    if (state.polling) return;
    state.polling = true;
    try {
      state.jobs = await api("jobs");
      renderJobs();
    } catch (err) {
      console.warn("jobs", err);
    } finally {
      state.polling = false;
    }
  }

  async function refreshHistory() {
    try {
      state.history = await api("history", 60);
      renderRecent();
      renderHistory();
    } catch (err) {
      console.warn("history", err);
    }
  }

  // ------------------------------------------------------------------ render status
  function renderStatus() {
    const s = state.status;
    if (!s) return;
    const bad = (s.engines || []).filter((e) => !e.ok).length || !s.proxy_ok;
    $("#engineDot").className = "pulse-dot" + (bad ? " bad" : "");
    $("#engineLabel").textContent = bad ? "有组件需要检查" : "引擎就绪";
    $("#engineList").innerHTML = (s.engines || []).map((e) => `
      <div class="engine-row" title="${esc(e.version)}">
        <span class="dot ${e.ok ? "" : "bad"}"></span>
        <span>${esc(e.name)}</span>
        <span class="ver">${esc(e.version || "")}</span>
      </div>`).join("");
    $("#proxyLabel").textContent = s.proxy + (s.proxy_ok ? " · 已连通" : " · 未连通");
    $("#proxyLabel").title = s.proxy;
    $("#diskFree").textContent = humanBytes(s.disk_free) + " 可用";
    $("#settingsProxy").textContent = s.proxy;
    $("#appVersion").textContent = "v" + (s.version || "1.1.0");
    $("#settingsEngines").innerHTML = (s.engines || []).map((e) => `
      <div class="settings-engine">
        <span class="dot ${e.ok ? "" : "bad"}"></span>
        <strong>${esc(e.name)}</strong>
        <span title="${esc(e.version)}">${esc(e.version || "")}</span>
      </div>`).join("");
  }

  // ------------------------------------------------------------------ render jobs
  function emptyState(icon, title, sub) {
    return `<div class="empty"><svg class="icon"><use href="#${icon}"/></svg><strong>${esc(title)}</strong><span>${esc(sub)}</span></div>`;
  }

  function jobCard(job) {
    const mode = modeOf(job);
    const status = job.status || "queued";
    const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
    const width = status === "done" ? 100 : percent;
    const meta = [];
    if (status === "running" || status === "queued") {
      meta.push(`${percent.toFixed(percent < 10 ? 1 : 0)}%`);
      if (job.total) meta.push(`${job.done_text} / ${job.total_text}`);
      else if (job.done) meta.push(job.done_text);
      if (job.speed_text) meta.push(job.speed_text);
    } else if (status === "done") {
      meta.push(job.done_text || "完成");
    } else if (job.error) {
      meta.push(job.error);
    }
    const canOpen = (job.files || []).length > 0;
    const actions = `
      ${status === "running" || status === "queued" ? `<button class="icon-btn sm" data-action="cancel" data-id="${esc(job.id)}" title="取消"><svg class="icon"><use href="#i-x"/></svg></button>` : ""}
      <button class="icon-btn sm" data-action="open" data-id="${esc(job.id)}" title="${canOpen ? "打开文件" : "打开下载目录"}"><svg class="icon"><use href="#${canOpen ? "i-external" : "i-folder"}"/></svg></button>`;
    const log = (job.log_tail || []).length ? `
      <details class="job-log"><summary>查看日志 · ${esc(phaseText(job.phase))}</summary><pre>${esc((job.log_tail || []).join("\n"))}</pre></details>` : "";
    return `
      <article class="job-card">
        <div class="job-top">
          <span class="job-icon"><svg class="icon"><use href="#${mode.icon}"/></svg></span>
          <div class="job-main">
            <div class="job-title" title="${esc(jobTitle(job))}">${esc(jobTitle(job))}</div>
            <div class="job-url" title="${esc(job.url)}">${esc(job.url)}</div>
          </div>
          <span class="job-status ${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>
          <span class="job-actions">${actions}</span>
        </div>
        <div class="progress-wrap">
          <div class="progress-meta"><span>${esc(phaseText(job.phase))}</span><span>${esc(meta.join(" · "))}</span></div>
          <div class="progress-track"><div class="progress-bar ${status === "running" ? "running" : ""}" style="width:${width}%"></div></div>
        </div>
        ${job.error ? `<div class="job-error">${esc(job.error)}</div>` : ""}
        ${log}
      </article>`;
  }

  function renderJobs() {
    const active = state.jobs.filter((j) => j.status === "running" || j.status === "queued");
    const all = state.jobs;
    $("#activeCount").textContent = active.length ? `${active.length} 个任务` : "暂无任务";
    $("#activeList").innerHTML = active.length
      ? active.map(jobCard).join("")
      : emptyState("i-download", "没有正在下载的任务", "在上方粘贴链接，按 Enter 开始。");
    $("#allJobs").innerHTML = all.length
      ? all.map(jobCard).join("")
      : emptyState("i-film", "还没有任务", "下载开始后会出现在这里。");
    const badge = $("#taskBadge");
    badge.textContent = String(active.length);
    badge.classList.toggle("hidden", active.length === 0);
  }

  // ------------------------------------------------------------------ render recent / history
  function renderRecent() {
    const items = (state.history || []).slice(0, 6);
    $("#recentList").innerHTML = items.length ? items.map((item) => {
      const file = (item.files || [])[0] || "";
      const mode = MODE[item.mode] || MODE.auto;
      return `
        <div class="recent-row">
          <span class="recent-icon"><svg class="icon"><use href="#${mode.icon}"/></svg></span>
          <div class="recent-main">
            <div class="recent-name" title="${esc(file || item.url)}">${esc(file ? fileName(file) : hostOf(item.url))}</div>
            <div class="recent-meta">${esc(shortDate(item.ts))} · ${esc(MODE[item.mode] ? MODE[item.mode].label : item.mode || "")}${item.exists === false ? " · 文件已移动" : ""}</div>
          </div>
          <span class="recent-size">${esc(item.bytes_text || humanBytes(item.bytes))}</span>
          <button class="icon-btn sm" data-action="history-open" data-path="${esc(file)}" title="打开"><svg class="icon"><use href="#i-external"/></svg></button>
        </div>`;
    }).join("") : emptyState("i-history", "还没有下载记录", "完成第一个任务后，这里会留下历史。");
  }

  function renderHistory() {
    const items = state.history || [];
    $("#historyList").innerHTML = items.length ? items.map((item) => {
      const file = (item.files || [])[0] || "";
      return `
        <div class="history-row">
          <span class="recent-icon"><svg class="icon"><use href="#${(MODE[item.mode] || MODE.auto).icon}"/></svg></span>
          <div class="history-main">
            <div class="history-title" title="${esc(file || item.url)}">${esc(file ? fileName(file) : item.title || hostOf(item.url))}</div>
            <div class="history-url" title="${esc(item.url)}">${esc(item.url)}</div>
          </div>
          <span class="history-date">${esc(shortDate(item.ts))}</span>
          <span class="history-badge ${item.ok ? "ok" : "fail"}">${item.ok ? "成功" : "失败"}</span>
          <span class="recent-size">${esc(item.bytes_text || humanBytes(item.bytes))}</span>
          <button class="icon-btn sm" data-action="history-open" data-path="${esc(file)}" title="打开"><svg class="icon"><use href="#i-external"/></svg></button>
        </div>`;
    }).join("") : emptyState("i-history", "没有历史", "下载一次后，记录会出现在这里。");
  }

  // ------------------------------------------------------------------ actions
  async function startDownload() {
    if (state.busy) return;
    const url = $("#urlInput").value.trim();
    if (!url) { $("#urlInput").focus(); toast("先粘贴一个链接", "bad"); return; }
    state.busy = true;
    $("#startBtn").disabled = true;
    $("#startBtn").innerHTML = `<svg class="icon"><use href="#i-refresh"/></svg>正在创建任务`;
    try {
      const payload = {
        url,
        mode: state.mode,
        quality: $("#quality").value,
        audio_format: $("#audioFormat").value,
        playlist: $("#optPlaylist").checked,
        cookies: $("#optCookies").checked,
        browser: $("#browser").value,
        subs: $("#optSubs").checked,
        force: $("#optForce").checked,
        flat: $("#optFlat").checked,
        out: $("#outDir").value.trim(),
        name: $("#outName").value.trim(),
        limit_rate: $("#limitRate").value.trim(),
      };
      const result = await api("start", payload);
      if (!result || !result.ok) throw new Error(result && result.error ? result.error : "无法创建任务");
      $("#urlInput").value = "";
      toast("已加入下载队列", "ok");
      await refreshJobs();
      schedulePoll(300);
      setView("tasks");
    } catch (err) {
      toast(err.message || String(err), "bad");
    } finally {
      state.busy = false;
      $("#startBtn").disabled = false;
      $("#startBtn").innerHTML = `<svg class="icon"><use href="#i-download"/></svg>开始下载`;
    }
  }

  async function cancelJob(id) {
    try {
      const result = await api("cancel", id);
      if (!result.ok) toast(result.error || "无法取消", "bad");
      await refreshJobs();
    } catch (err) { toast(String(err), "bad"); }
  }

  async function openJob(id) {
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return;
    const path = (job.files || [])[0];
    try {
      if (path) await api("open_path", path);
      else await api("open_downloads");
    } catch (err) { toast(String(err), "bad"); }
  }

  async function openPath(path) {
    if (!path) { toast("没有可打开的文件", "bad"); return; }
    try {
      const result = await api("open_path", path);
      if (result && !result.ok) toast(result.error || "打开失败", "bad");
    } catch (err) { toast(String(err), "bad"); }
  }

  async function pasteClipboard() {
    try {
      let text = "";
      try { text = await navigator.clipboard.readText(); } catch { text = ""; }
      if (!text) text = await api("read_clipboard");
      if (text) { $("#urlInput").value = text.trim(); $("#urlInput").focus(); }
      else toast("剪贴板为空", "bad");
    } catch (err) { toast("无法读取剪贴板", "bad"); }
  }

  async function browseInto(input) {
    try {
      const folder = await api("pick_folder");
      if (folder) input.value = folder;
    } catch (err) { toast(String(err), "bad"); }
  }

  // ------------------------------------------------------------------ settings
  function fillSettings(status) {
    const c = status.config || {};
    $("#setProxy").value = c.proxy || "";
    $("#setRoot").value = c.downloadRoot || "downloads";
    $("#setBrowser").value = c.browser || "edge";
    $("#setDates").checked = c.dateSubfolders !== false;
    $("#setMetadata").checked = c.embedMetadata !== false;
  }

  async function saveSettings() {
    try {
      const payload = {
        proxy: $("#setProxy").value.trim(),
        downloadRoot: $("#setRoot").value.trim() || "downloads",
        browser: $("#setBrowser").value,
        dateSubfolders: $("#setDates").checked,
        embedMetadata: $("#setMetadata").checked,
      };
      const result = await api("save_config", payload);
      if (!result || !result.ok) throw new Error("保存失败");
      state.status = result.status;
      renderStatus();
      $("#saveState").textContent = "已保存";
      setTimeout(() => { $("#saveState").textContent = ""; }, 2200);
      toast("设置已保存", "ok");
    } catch (err) { toast(err.message || String(err), "bad"); }
  }

  // ------------------------------------------------------------------ view/theme
  const VIEW_META = {
    download: ["下载", "把链接变成文件，引擎自动选择。"],
    tasks: ["任务", "查看进度、日志和已完成的任务。"],
    history: ["历史", "每一次下载的落点与结果。"],
    settings: ["设置", "代理、目录和引擎状态。"],
  };

  function setView(view) {
    state.view = view;
    $$(".view").forEach((el) => el.classList.toggle("active", el.id === "view-" + view));
    $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
    const meta = VIEW_META[view] || VIEW_META.download;
    $("#pageTitle").textContent = meta[0];
    $("#pageSub").textContent = meta[1];
    if (view === "history") refreshHistory();
    if (view === "settings") refreshStatus();
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("fetchdesk-theme", theme);
    const use = $("#themeBtn use");
    if (use) use.setAttribute("href", theme === "dark" ? "#i-sun" : "#i-moon");
  }

  function bind() {
    $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
    $$("[data-view]").forEach((btn) => {
      if (!btn.classList.contains("nav-item")) btn.addEventListener("click", () => setView(btn.dataset.view));
    });
    $$(".chip[data-mode]").forEach((chip) => chip.addEventListener("click", () => {
      state.mode = chip.dataset.mode;
      $$(".chip[data-mode]").forEach((c) => c.classList.toggle("active", c === chip));
      $("#audioFormatWrap").hidden = state.mode !== "audio";
      $("#quality").disabled = ["images", "file", "article", "torrent"].includes(state.mode);
      $("#quality").closest(".inline-field").style.opacity = $("#quality").disabled ? ".45" : "1";
    }));
    $$("[data-quick]").forEach((card) => card.addEventListener("click", () => {
      const mode = card.dataset.quick;
      const chip = $(`.chip[data-mode="${mode}"]`);
      if (chip) chip.click();
      $("#urlInput").focus();
      toast(`已切换到${MODE[mode].label}模式，粘贴链接即可`, "");
    }));
    $("#startBtn").addEventListener("click", startDownload);
    $("#pasteBtn").addEventListener("click", pasteClipboard);
    $("#browseOut").addEventListener("click", () => browseInto($("#outDir")));
    $("#browseRoot").addEventListener("click", () => browseInto($("#setRoot")));
    $("#openFolderBtn").addEventListener("click", async () => {
      try { await api("open_downloads"); } catch (err) { toast(String(err), "bad"); }
    });
    $("#refreshHistory").addEventListener("click", refreshHistory);
    $("#clearTasks").addEventListener("click", async () => {
      try { await api("clear_finished"); await refreshJobs(); toast("已清理结束任务", "ok"); }
      catch (err) { toast(String(err), "bad"); }
    });
    $("#saveSettings").addEventListener("click", saveSettings);
    $("#themeBtn").addEventListener("click", () => {
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    $("#advToggle").addEventListener("click", () => {
      const open = $("#advToggle").getAttribute("aria-expanded") === "true";
      $("#advToggle").setAttribute("aria-expanded", String(!open));
      $("#advanced").hidden = open;
    });
    $("#urlInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); startDownload(); }
    });
    document.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-action]");
      if (!btn) return;
      if (btn.dataset.action === "cancel") cancelJob(btn.dataset.id);
      if (btn.dataset.action === "open") openJob(btn.dataset.id);
      if (btn.dataset.action === "history-open") openPath(btn.dataset.path);
    });
  }

  // ------------------------------------------------------------------ start
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();