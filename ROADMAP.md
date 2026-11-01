# Roadmap

## v1.0 — 下载工作台（已完成）

- 一条命令自动路由视频、音频、图片、文件、文章、种子。
- 代理自动探测、断点续传、归档去重、历史记录。
- 项目内 `download` 技能 + 站点/排障参考文档。
- 可复现安装：`setup.ps1` + `bootstrap.py`。

## v1.1 — 桌面 UI（已完成）

- FetchDesk：侧边导航、链接主输入、类型/画质、高级选项、任务进度、日志、历史、设置。
- 本地 HTTP API + Edge `--app` 窗口；自定义图标与桌面快捷方式。
- `--progress-file` 结构化进度，CLI 与 GUI 共用同一套下载实现。
- 无头验证 API、静态资源、任务执行、进度和历史；GUI 窗口在普通桌面会话启动。


## v2.0 — Skill / 插件侦察（Scout，v2.0 已完成只读推荐）

### 目标

用户在工作台用自然语言描述「我要做的项目、功能和目的」，系统给出：

1. GitHub 上匹配的高分 skill（含仓库链接、star、更新时间、license、匹配理由、风险）。
2. 可安装的 DSH 插件 / MCP 连接（含包名、版本、来源、权限与风险）。
3. 如果两者都没有合适结果，生成一个可用的 skill 或插件骨架，校验后安装到项目。

核心原则：**先推荐，再安装；安装前必须让人看见证据和风险。**

### 命令面

```bat
scout advise "我要做一个每周自动汇总 B 站收藏视频并提取音频的工作流"
scout skills "pdf 转 markdown"
scout plugins "postgres mcp"
scout install skill <owner/repo> --name <name>
scout install plugin <npm-package> --dry-run
scout new skill <name> --description "..."
scout new plugin <name> --description "..."
```

`advise` 输出 Markdown + JSON 两份结果；JSON 供后续安装步骤消费。

### 数据源

| 来源 | 用途 | 认证 |
|---|---|---|
| GitHub REST search/repositories | 按 topic、描述、README 关键词找 skill 仓库 | 可选 `GITHUB_TOKEN`（未认证 60 次/小时） |
| GitHub raw / git clone | 读取 `SKILL.md`、README、license | 走代理 |
| npm registry search | 找 `dsh-plugin`、`dsh-*`、MCP 相关包 | 无 |
| DSH plugin catalog | 已安装 bundle、可安装 bundle、版本约束 | 本地 `plugin_manager` |
| 本地技能目录 | 避免重复推荐已有 `.dsh/skills/*` | 本地 |
| awesome 列表 | `awesome-claude-skills`、`awesome-agent-skills` 等索引 | 无 |

### 评分模型（初版）

```
score = 0.40 * relevance
      + 0.25 * popularity   # log(stars) 归一化
      + 0.15 * freshness    # pushed_at 衰减
      + 0.12 * compatibility# SKILL.md/DSH manifest、license、无二进制
      + 0.08 * trust        # owner 类型、archived、release 记录
```

硬过滤：archived、无 license（降级并标注）、包含 `curl | bash`、下载并执行未知二进制、混淆脚本、超大仓库、与目标平台不兼容。

输出 Top 3，并显示「为什么是它 / 为什么不是更高分」以及「不推荐」列表。

### 安装与校验

Skill：
- 只取 `SKILL.md` 及其 `references/`、`scripts/`、`assets/`。
- 校验 frontmatter（name/description 必填、kebab-case）。
- 静态扫描危险命令与外部下载；默认不执行仓库内脚本。
- 安装到 `.dsh/skills/<name>/`，写 `state/scout-installs.jsonl`。

Plugin：
- 默认只做 dry-run，展示包名、版本、依赖、安装脚本、权限。
- 必须显式确认后才调用 `plugin_manager`；记录来源与版本。
- DSH 版本不满足 `engines.dsh` 时拒绝，不做版本豁免。

### 自动生成

没有合适结果时：

- `new skill`：生成 `SKILL.md` + `references/` + 可选 `scripts/` 模板，填入目标、触发条件、步骤、验证、失败处理，然后本地校验并安装。
- `new plugin`：生成最小 host 插件（`package.json`、`lib/index.js`、`cordis.patch.yml`、README），本机可构建时执行构建与加载验证；不能构建则输出待接入清单。

生成物必须包含：用途、触发条件、输入输出、权限、失败模式、验证命令。禁止生成空壳。

### 安全边界

- 不自动执行远程仓库的 install/postinstall 脚本。
- 不自动启用未知插件；不绕过 DSH 的版本/权限约束。
- 不采集私有仓库；token 只从环境变量读取，不落盘、不回显。
- 推荐结果必须带来源 URL 与抓取时间，避免「幻觉插件」。

### 验收标准

- 给定「下载 B 站视频并提取音频」：推荐本地 `download` 技能，并说明 `dl.cmd audio` 用法。
- 给定「Excel 报表」：推荐本地 `office-xlsx`，不再重复安装同类 skill。
- 给定「PDF 转 Markdown」：能给出 2-3 个 GitHub 候选，按分数排序并标风险。
- 给定「Postgres MCP」：能区分 MCP server 与 DSH 插件，给出配置草案。
- 给定完全冷门需求：生成 skill，`dl.cmd` 同类校验通过，且 `SKILL.md` 可被 DSH 发现。
- 无网络/无 token：返回缓存结果并明确标注「可能过期」。

### 里程碑

1. v2.0：GitHub/npm 搜索 + 评分 + Markdown/JSON 报告（已完成）。
2. v2.1：skill 安装/校验、本地去重、缓存与 token。
3. v2.2：插件 dry-run/安装、生成器、验收用例。

### 非目标

- 不做通用代码搜索代理，不替代 GitHub 本身。
- 不自动安装任意第三方代码。
- 不承诺「最高分 = 最适合」；评分只是排序，最终由人确认。
