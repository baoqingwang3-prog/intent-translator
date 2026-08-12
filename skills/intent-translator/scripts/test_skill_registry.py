#!/usr/bin/env python3
"""Regression tests for Skill discovery, registry search, and Markdown catalog generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discover_skills import discover_skills
from skill_registry import render_markdown, search_registry


def write_skill(root: Path, folder: str, name: str, description: str) -> Path:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_md


class SkillRegistryTests(unittest.TestCase):
    def test_discovery_ignores_retired_folders_and_reports_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selected = write_skill(root, "alpha", "alpha", "Diagnose alpha failures")
            write_skill(root, "second-alpha", "alpha", "Alternate alpha")
            write_skill(root, ".backup-old/hidden", "hidden", "Must not be discovered")
            write_skill(root, ".archive-old/hidden", "archived", "Must not be discovered")
            write_skill(root, ".retired-old/hidden", "retired", "Must not be discovered")

            registry = discover_skills([root])

            self.assertEqual(registry["schema_version"], 2)
            self.assertEqual(registry["summary"], {"selected": 1, "duplicate_names": 1, "errors": 0})
            self.assertEqual(registry["skills"][0]["skill_md"], str(selected.resolve()))
            self.assertEqual(len(registry["skills"][0]["sha256"]), 64)
            self.assertEqual(registry["duplicates"][0]["name"], "alpha")

    def test_query_and_markdown_catalog_use_metadata_not_full_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_skill(root, "diagnosing-bugs", "diagnosing-bugs", "Diagnose hard regressions")
            write_skill(root, "docx", "docx", "Create and edit Word documents")
            registry = discover_skills([root])

            matches = search_registry(registry, "diagnose regression")
            chinese_matches = search_registry(registry, "诊断困难 bug 回归测试")
            catalog = render_markdown(registry)

            self.assertEqual(matches[0]["name"], "diagnosing-bugs")
            self.assertEqual(chinese_matches[0]["name"], "diagnosing-bugs")
            self.assertIn("# Local Skill Capability Map", catalog)
            self.assertIn("`diagnosing-bugs`", catalog)
            self.assertNotIn("# diagnosing-bugs", catalog)


if __name__ == "__main__":
    unittest.main()
