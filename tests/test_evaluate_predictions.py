import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evaluate_predictions import evaluate  # noqa: E402


class EvaluatePredictionsTests(unittest.TestCase):
    def test_scores_fields_and_reports_missing_cases(self):
        cases = [
            {
                "id": "one",
                "expected": {
                    "path": "fast",
                    "mode": "diagnose",
                    "memory_action": "none",
                    "clarification": False,
                    "primary_skill": None,
                    "preserve_voice": True,
                },
            },
            {
                "id": "two",
                "expected": {
                    "path": "review",
                    "mode": "build",
                    "memory_action": "none",
                    "clarification": True,
                    "primary_skill": "skill-creator",
                    "preserve_voice": True,
                },
            },
        ]
        predictions = [
            {
                "id": "one",
                "path": "fast",
                "mode": "diagnose",
                "memory_action": "none",
                "clarification": False,
                "primary_skill": None,
                "preserve_voice": True,
            }
        ]
        result = evaluate(cases, predictions)
        self.assertEqual(result["missing_ids"], ["two"])
        self.assertEqual(result["overall_accuracy"], 1.0)
        self.assertEqual(result["scored_fields"], 6)

    def test_detects_wrong_prediction(self):
        cases = [{"id": "one", "expected": {"path": "review", "mode": "build"}}]
        predictions = [{"id": "one", "path": "fast", "mode": "build"}]
        result = evaluate(cases, predictions)
        self.assertEqual(result["field_accuracy"]["path"], 0.0)
        self.assertEqual(result["field_accuracy"]["mode"], 1.0)
        self.assertEqual(result["overall_accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
