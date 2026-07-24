import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from discover_skills import default_roots, discover_skills, parse_frontmatter  # noqa: E402


class DiscoverSkillsTests(unittest.TestCase):
    def write_skill(self, root: Path, folder: str, frontmatter: str) -> Path:
        skill_dir = root / folder
        skill_dir.mkdir(parents=True)
        path = skill_dir / "SKILL.md"
        path.write_text(f"---\n{frontmatter}\n---\n\n# Body\n", encoding="utf-8")
        return path

    def test_parses_quoted_and_folded_descriptions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            quoted = self.write_skill(root, "quoted", 'name: quoted\ndescription: "A quoted skill"')
            folded = self.write_skill(
                root,
                "folded",
                "name: folded\ndescription: >\n  First line\n  second line\ndisable-model-invocation: true",
            )
            self.assertEqual(parse_frontmatter(quoted)["description"], "A quoted skill")
            folded_data = parse_frontmatter(folded)
            self.assertEqual(folded_data["description"], "First line second line")
            self.assertTrue(folded_data["disable-model-invocation"])

    def test_first_root_wins_and_duplicates_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = base / "first"
            second = base / "second"
            self.write_skill(first, "router", "name: router\ndescription: First")
            self.write_skill(second, "router", "name: router\ndescription: Second")
            self.write_skill(second, "other", "name: other\ndescription: Other")

            registry = discover_skills([first, second])
            skills = {item["name"]: item for item in registry["skills"]}
            self.assertEqual(skills["router"]["description"], "First")
            self.assertEqual([item["name"] for item in registry["duplicates"]], ["router"])
            self.assertEqual(set(skills), {"router", "other"})

    def test_invalid_skill_is_reported_without_stopping_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write_skill(root, "good", "name: good\ndescription: Works")
            self.write_skill(root, "bad", "name: bad")
            registry = discover_skills([root])
            self.assertEqual([item["name"] for item in registry["skills"]], ["good"])
            self.assertEqual(len(registry["errors"]), 1)

    def test_default_roots_support_configured_codex_claude_and_shared_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            configured = base / "custom"
            roots = default_roots(
                cwd=base / "project",
                home=base / "home",
                env={
                    "CODEX_HOME": str(base / "codex"),
                    "CLAUDE_CONFIG_DIR": str(base / "claude"),
                    "INTENT_TRANSLATOR_SKILL_ROOTS": str(configured),
                },
            )
            self.assertEqual(roots[0], configured.resolve())
            self.assertIn((base / "codex" / "skills").resolve(), roots)
            self.assertIn((base / "claude" / "skills").resolve(), roots)
            self.assertIn((base / "home" / ".agents" / "skills").resolve(), roots)
            self.assertIn((base / "home" / ".cursor" / "skills").resolve(), roots)
            self.assertIn((base / "home" / ".gemini" / "skills").resolve(), roots)
            self.assertIn((base / "home" / ".copilot" / "skills").resolve(), roots)


if __name__ == "__main__":
    unittest.main()
