import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from compose_skills import plan_composition  # noqa: E402


def registry(*names: str) -> dict:
    return {
        "skills": [
            {"name": name, "description": name, "path": f"/skills/{name}"}
            for name in names
        ]
    }


class SkillCompositionTests(unittest.TestCase):
    def test_search_report_uses_research_and_renderer_with_dormant_fallback(self):
        result = plan_composition(
            "全网搜一下最新 AI 缓存实践，整理成 docx 报告",
            "",
            registry("agent-reach", "smart-search", "research", "docx"),
        )

        self.assertEqual(result["primary_skill"], "agent-reach")
        self.assertEqual(result["post_skills"], ["research", "docx"])
        self.assertEqual(result["fallback_skills"], ["smart-search"])
        self.assertLessEqual(result["composition_size"], 4)

    def test_diagnosis_fix_keeps_diagnosis_implementation_and_review_separate(self):
        result = plan_composition(
            "这个接口偶发 500，帮我诊断并修复",
            "",
            registry("diagnosing-bugs", "tdd", "code-review"),
        )

        self.assertEqual(result["primary_skill"], "diagnosing-bugs")
        self.assertEqual(result["post_skills"], ["tdd", "code-review"])

    def test_study_orchestrator_exposes_only_the_explicit_child(self):
        result = plan_composition(
            "继续复习模电，然后出题考我",
            "",
            registry("study-assistant", "study-quiz", "study-teach"),
        )

        self.assertEqual(result["primary_skill"], "study-assistant")
        self.assertEqual(result["post_skills"], ["study-quiz"])

    def test_requested_missing_primary_is_reported_without_substitution(self):
        result = plan_composition(
            "do the task",
            "",
            registry("research"),
            requested_primary="agent-reach",
        )

        self.assertIsNone(result["primary_skill"])
        self.assertEqual(result["missing_skills"], ["agent-reach"])


if __name__ == "__main__":
    unittest.main()
