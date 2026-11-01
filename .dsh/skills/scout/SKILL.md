---
name: scout
description: Recommend high-star GitHub Agent Skills and DSH plugins for a described project goal. Reads SKILL.md evidence, ranks by relevance/popularity/freshness, checks local skills first, and reports links, risks, and install hints without installing anything. Use when the user describes what they want to build and asks for suitable skills/plugins.
whenToUse: The user says "what skill/plugin should I use", describes a project goal, asks to find high-star GitHub skills, or wants DSH plugin/MCP recommendations. Also use before authoring a new skill to avoid duplicating an existing one.
---

# Scout

Scout answers one question: **for this goal, what is already good enough to reuse?**

It is read-only in v2.0. It searches, reads, scores, and reports. It does not install, execute, or enable anything.

## Quick start

```bat
scout.cmd advise "下载 B 站视频并提取音频" --save
scout.cmd skills "把 PDF 转成 Markdown"
scout.cmd plugins "postgres mcp"
scout.cmd doctor
```

`advise` prints Markdown and saves a report under `reports\` when `--save` is used. Add `--json` for automation.

## Workflow

1. Run `scout.cmd doctor` if this is the first use or search looks broken.
2. Run `scout.cmd advise "<goal>" --limit 5`.
3. Read the report in this order:
   - **本地已有** — reuse before installing.
   - **GitHub Skills** — inspect the linked `SKILL.md`, license, and risks.
   - **插件 / MCP** — inspect capabilities (`shell`, `fs-write`, `network`) and red lines.
4. Present a compact shortlist to the user: name, what it does, score, stars, updated date, license, risk, link.
5. If nothing fits, say so explicitly and propose authoring a project skill. v2.2 adds `scout new skill`.

## What the report means

- **Score**: relevance 50%, stars 20%, freshness 12%, compatibility 10%, trust 8%.
- **Local** candidates are already installed; their score is a relevance signal, not a quality ranking.
- **Risks** are evidence-based: missing SKILL.md, no license, dangerous shell patterns, plugin capabilities, or missing npm release.
- A high star count cannot rescue a low relevance candidate; irrelevant popular repos are filtered.
- `suggest_generate: true` means no existing result cleared the bar.

## Commands

| Command | Purpose |
|---|---|
| `advise "<goal>"` | skills + plugins + local |
| `skills "<goal>"` | GitHub skills only |
| `plugins "<goal>"` | plugins/MCP only |
| `--limit N` | 1–10 results per section |
| `--refresh` | ignore the 24h cache |
| `--json` | JSON only |
| `--save` | write `reports/scout-*.md` and `.json` |
| `--no-token` | anonymous GitHub search |
| `--proxy` / `--no-proxy` | override proxy |
| `doctor` | token/proxy/cache status |

## Data and limits

- GitHub repository search + code search (`filename:SKILL.md`), with a token from `GITHUB_TOKEN`, `.env`, or Git Credential Manager.
- Public DSH plugin registry `https://awesome-dsh-plugin.com/plugins.json` (cached 24h).
- npm registry search for packages the registry misses, and MCP servers when the goal mentions MCP.
- Local skills from `.dsh/skills`, `~/.dsh/skills`, `~/.agents/skills`, and bundled office skills.
- GitHub anonymous search is rate-limited; token is optional but recommended. Never print or commit the token.
- The plugin registry is third-party data; verify the linked repository before installing.

## Guardrails

- Do not install or enable a plugin from Scout output without user confirmation.
- Do not run install scripts from a recommended repo.
- Treat a skill's `scripts/` as untrusted until reviewed.
- If a candidate lacks a license or has dangerous patterns, say so before recommending it.
- Cite the repository or registry URL for every recommendation.

## Reference

- `references/scoring.md` — weights, sources, cache behavior, and tuning.