#!/usr/bin/env python3
"""Offline tests for the Scout ranking and parsing helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scout  # noqa: E402


class ScoutTextTests(unittest.TestCase):
    def test_goal_terms_direct_english_first(self) -> None:
        terms = scout.goal_terms("用 Excel 做销售报表并生成图表")
        self.assertEqual(terms[0], "excel")
        self.assertIn("xlsx", terms)
        self.assertIn("chart", terms)

    def test_goal_profile_detects_bilibili_and_download(self) -> None:
        profile = scout.goal_profile("下载 B 站视频并提取音频")
        self.assertIn("download", profile["actions"])
        self.assertIn("extract", profile["actions"])
        self.assertIn("bilibili", profile["entities"])
        self.assertIn("b站", profile["entity_terms"])

    def test_strong_match_rejects_video_generation_for_download(self) -> None:
        profile = scout.goal_profile("下载 B 站视频并提取音频")
        self.assertFalse(scout.has_strong_match(profile, "video-generation", "generate video from a prompt"))
        self.assertTrue(scout.has_strong_match(profile, "bilibili-download", "download and extract audio from Bilibili video"))

    def test_game_and_novel_goals_have_english_terms(self) -> None:
        self.assertIn("game", scout.goal_terms("我想自己开发一个游戏"))
        self.assertIn("novel", scout.goal_terms("写小说"))
        self.assertIn("develop", scout.goal_profile("我想自己开发一个游戏")["actions"])
        self.assertIn("write", scout.goal_profile("写小说")["actions"])

    def test_term_boundaries_avoid_workbook_false_positive(self) -> None:
        self.assertFalse(scout.term_in("book", "excel workbook"))
        self.assertTrue(scout.term_in("book", "a book about writing"))

    def test_parse_frontmatter(self) -> None:
        text = '---\nname: demo-skill\ndescription: "A demo"\nwhenToUse: |\n  when testing\n---\n\n# Body\n'
        meta = scout.parse_frontmatter(text)
        self.assertEqual(meta["name"], "demo-skill")
        self.assertEqual(meta["description"], "A demo")
        self.assertIn("when testing", meta["whenToUse"])

    def test_choose_skill_path_ignores_agent_skill_doc(self) -> None:
        paths = ["docs/ai/agent-skill.md", "skills/pdf/SKILL.md", "SKILL.md"]
        chosen = scout.choose_skill_path(paths, ["pdf"])
        self.assertNotIn("docs/ai/agent-skill.md", chosen)
        self.assertIn("SKILL.md", chosen)

    def test_local_relevance(self) -> None:
        self.assertGreater(scout.local_relevance(["excel", "xlsx"], "office-xlsx", "Excel workbooks"), 0.4)

    def test_render_markdown_has_sections(self) -> None:
        result = {
            "goal": "demo",
            "generated_at": "now",
            "token_source": "none",
            "proxy": "direct",
            "stats": {"local": 0, "skills": 0, "plugins": 0, "api_calls": 0, "seconds": 0},
            "local": [],
            "skills": [],
            "plugins": [],
            "warnings": [],
            "suggest_generate": True,
        }
        markdown = scout.render_markdown(result)
        self.assertIn("# Scout", markdown)
        self.assertIn("GitHub Skills", markdown)
        self.assertIn("插件 / MCP", markdown)


if __name__ == "__main__":
    unittest.main()