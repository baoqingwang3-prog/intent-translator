import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from stranger_smoke import run_smoke  # noqa: E402


class StrangerSmokeTests(unittest.TestCase):
    def test_two_strangers_create_and_invoke_isolated_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_smoke(Path(temp))
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["metrics"]["users_tested"], 2)
        self.assertEqual(report["metrics"]["technical_terms_exposed"], 0)
        self.assertEqual(report["metrics"]["cross_contamination_count"], 0)
        self.assertEqual(report["metrics"]["skills_created_and_invoked"], 2)
        self.assertTrue(report["metrics"]["first_correction_effective"])
        self.assertFalse(report["real_button_ui_complete"])


if __name__ == "__main__":
    unittest.main()
