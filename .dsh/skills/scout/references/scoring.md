# Scout scoring and sources

## Sources

| Source | What it gives | Notes |
|---|---|---|
| GitHub repository search | stars, description, license, pushed_at | `in:name,description,readme` + skill topics |
| GitHub code search | exact `SKILL.md` paths for a goal | requires a token; 10 searches/min |
| GitHub tree/raw | verified SKILL.md body, frontmatter, risks | one tree + one raw per candidate |
| awesome-dsh-plugin | 8k+ curated DSH plugins with capabilities | 10 MB JSON, cached 24h |
| npm registry | packages missing from the registry, MCP servers | no star data |

## Score

```
score = 0.50 * relevance
      + 0.20 * popularity   # log10(stars) / 5
      + 0.12 * freshness    # 90d=1.0, 1y=0.8, 2y=0.5, older=0.2
      + 0.10 * compatibility
      + 0.08 * trust
```

Relevance uses direct English words first, then a Chinese synonym map, then
Chinese bigrams. A candidate must clear an intent check:

- The goal's action (download / convert / summarize / generate...) must appear in
  the candidate's name, description, or `whenToUse`, **or**
- the goal names a platform (Bilibili, YouTube, WeChat...) and the candidate
  mentions that platform plus a content term.

This is why a 90k-star "video generation" repo does not outrank a 500-star
"video download" skill.

## Hard filters and penalties

- archived repos: skipped
- repo bigger than 300 MB: skipped
- no `SKILL.md`: kept only as an unverified repo-level suggestion
- missing license: risk note + trust penalty
- dangerous patterns (`curl | sh`, encoded PowerShell, `rm -rf /`, base64 pipe):
  risk note + 8% score penalty
- plugin capabilities `shell`, `fs-write`, `network`, `env`, `subagent`:
  surfaced as permission risks

## Cache

- Report cache: `state/scout/cache.json`, 24h, keyed by goal + limit + token mode.
- Plugin registry: `state/scout/plugins.json`, 24h.
- `--refresh` bypasses both.
- Reports saved with `--save` go to `reports/` (gitignored only if the user chooses).

## Tuning

- `MAX_REPOS = 9` limits tree/raw calls per run.
- `MAX_CODE_RESULTS = 10` limits the code-search supplement.
- Increase `--limit` to see more candidates; the score is not a probability.
- The ranking is a shortlist, not an autopilot. Read the linked evidence.