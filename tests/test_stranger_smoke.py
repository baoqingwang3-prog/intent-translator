import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from stranger_smoke import run_smoke  # noqa: E402


class StrangerSmokeTests(unittest.TestCase):
    def test_five_strangers_cover_alpha_safety_and_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_smoke(Path(temp))
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["metrics"]["users_tested"], 5)
        self.assertEqual(report["metrics"]["technical_terms_exposed"], 0)
        self.assertEqual(report["metrics"]["cross_contamination_count"], 0)
        self.assertEqual(report["metrics"]["skills_created_and_invoked"], 5)
        self.assertEqual(report["metrics"]["wrong_routes"], 0)
        self.assertEqual(report["metrics"]["unnecessary_questions"], 0)
        self.assertEqual(report["metrics"]["dangerous_confirmation_misses"], 0)
        self.assertEqual(report["metrics"]["correction_recurrences"], 0)
        self.assertTrue(report["metrics"]["first_correction_effective"])
        self.assertTrue(all(item["generic_before_onboarding"] for item in report["users"].values()))
        self.assertFalse(report["real_button_ui_complete"])


if __name__ == "__main__":
    unittest.main()
