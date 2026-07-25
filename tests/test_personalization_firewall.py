import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_profile import default_profile  # noqa: E402
from personalization_audit import audit_repository  # noqa: E402
from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


class PersonalizationFirewallTests(unittest.TestCase):
    def compile_with_profile(self, temp: str, profile: dict, utterance: str):
        path = Path(temp) / "profile.json"
        path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(path),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            return IntentCompiler(registry={"skills": [], "errors": []}).compile(
                CompileRequest(utterance=utterance, semantic_mode="off")
            )

    def test_clean_profile_contains_no_creator_shadow(self):
        serialized = json.dumps(default_profile(), ensure_ascii=False)
        for forbidden in ("example-creator-handle", "考研", "雅思", "ENTP", "PUA", "D:\\测试"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(default_profile()["phrase_mappings"], {})
        self.assertNotIn("student_state", default_profile())

    def test_clean_room_profile_init_is_generic(self):
        with tempfile.TemporaryDirectory() as temp:
            profile_path = Path(temp) / "home" / ".intent-translator" / "profile.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS / "init_profile.py"), "init", "--profile", str(profile_path)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(profile["phrase_mappings"], {})
            self.assertEqual(profile["adaptation"]["domains"], [])
            self.assertNotIn("study", profile)
            self.assertNotIn("student_life", profile)

    def test_opposite_profiles_explainably_compile_same_phrase_differently(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            build_profile = default_profile()
            build_profile["phrase_mappings"]["走起"] = {
                "meaning": "build and implement a new tool",
                "scope": "global",
            }
            answer_profile = default_profile()
            answer_profile["phrase_mappings"]["走起"] = {
                "meaning": "answer only with a short explanation",
                "scope": "global",
            }
            build = self.compile_with_profile(left, build_profile, "走起")
            answer = self.compile_with_profile(right, answer_profile, "走起")
            self.assertEqual(build["mode"], "build")
            self.assertEqual(answer["mode"], "answer")
            self.assertEqual(build["phrase_match"]["phrase"], "走起")
            self.assertEqual(answer["phrase_match"]["phrase"], "走起")

    def test_deleting_profile_restores_generic_behavior(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = default_profile()
            profile["phrase_mappings"]["走起"] = "build and implement a new tool"
            personalized = self.compile_with_profile(temp, profile, "走起")
            Path(temp, "profile.json").unlink()
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
                },
            ):
                generic = IntentCompiler(registry={"skills": [], "errors": []}).compile(
                    CompileRequest(utterance="走起", semantic_mode="off")
                )
            self.assertEqual(personalized["mode"], "build")
            self.assertEqual(generic["mode"], "answer")
            self.assertIsNone(generic["phrase_match"])
            self.assertFalse(generic["study_context"]["enabled"])
            self.assertFalse(generic["student_state"]["enabled"])

    def test_short_utterance_does_not_match_a_longer_confirmed_phrase(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = default_profile()
            profile["phrase_mappings"]["you can consider"] = {
                "meaning": "explore options without publishing",
                "scope": "global",
            }
            short = self.compile_with_profile(temp, profile, "consider")
            full = self.compile_with_profile(temp, profile, "you can consider this approach")
            self.assertIsNone(short["phrase_match"])
            self.assertEqual(full["phrase_match"]["phrase"], "you can consider")

    def test_repository_contamination_metrics_are_zero(self):
        private_terms = [
            "definitely-not-" + "present-private-handle",
            "大学生" + "状态.md",
            "意图中枢-" + "学习索引.md",
        ]
        report = audit_repository(REPO_ROOT, private_terms=private_terms)
        self.assertEqual(report["creator_shadow_leakage"], 0)
        self.assertEqual(report["default_user_contamination_rate"], 0.0)
        self.assertEqual(report["findings"], [])
        self.assertGreater(report["tracked_text_files"], 20)
        self.assertEqual(report["private_terms_checked"], len(private_terms))


if __name__ == "__main__":
    unittest.main()
