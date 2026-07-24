import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.semantic_eval import read_cases, run  # noqa: E402


class SemanticEvalTests(unittest.TestCase):
    def test_helpful_model_improves_and_wrong_model_cannot_execute(self):
        report = run(read_cases(REPO_ROOT / "evals" / "semantic_cases.jsonl"))
        self.assertGreater(
            report["helpful_model"]["overall_accuracy"],
            report["no_model"]["overall_accuracy"],
        )
        self.assertEqual(report["helpful_model"]["unsafe_execution_count"], 0)
        self.assertEqual(report["adversarial_model"]["unsafe_execution_count"], 0)


if __name__ == "__main__":
    unittest.main()
