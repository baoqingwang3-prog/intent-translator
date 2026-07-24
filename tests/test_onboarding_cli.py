import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "intent-translator" / "scripts" / "onboard.py"


class OnboardingCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def test_status_is_jargon_free_and_admits_generic_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            result = self.run_cli("status", "--profile", str(profile), "--language", "zh-CN")
            self.assertEqual(result["mode"], "generic")
            self.assertIn("没有个人记忆", result["message"])
            visible = json.dumps(result, ensure_ascii=False)
            for term in ("ExecutionEnvelope", "MCP", "SQLite", "prompt", "ENTP", "PUA"):
                self.assertNotIn(term, visible)

    def test_initialized_default_profile_still_reports_generic_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "skills" / "intent-translator" / "scripts" / "init_profile.py"),
                    "init",
                    "--profile",
                    str(profile),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = self.run_cli("status", "--profile", str(profile), "--language", "zh-CN")
            self.assertEqual(result["mode"], "generic")

    def test_apply_only_sets_three_onboarding_categories_and_preserves_existing_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            self.run_cli(
                "apply",
                "--profile",
                str(profile),
                "--memory",
                "local",
                "--interpretation",
                "choices",
                "--tone",
                "concise",
                "--sharp-review",
                "off",
                "--language",
                "zh-CN",
            )
            data = json.loads(profile.read_text(encoding="utf-8"))
            data["phrase_mappings"]["开整"] = "开始执行"
            profile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(
                "apply",
                "--profile",
                str(profile),
                "--memory",
                "skip",
                "--interpretation",
                "ask",
                "--tone",
                "detailed",
                "--sharp-review",
                "on",
                "--language",
                "zh-CN",
            )
            updated = json.loads(profile.read_text(encoding="utf-8"))
            self.assertTrue(result["completed"])
            self.assertEqual(updated["phrase_mappings"]["开整"], "开始执行")
            self.assertEqual(updated["interpretation_preferences"]["material_ambiguity"], "ask")
            self.assertEqual(updated["response_style"]["verbosity"], "detailed")
            self.assertTrue(updated["review_preferences"]["sharp_review"])
            self.assertNotIn("study", updated)
            self.assertNotIn("student_life", updated)
            self.assertNotIn("spend_guard", updated["risk_policy"])


if __name__ == "__main__":
    unittest.main()
