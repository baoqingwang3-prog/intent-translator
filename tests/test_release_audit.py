import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from release_audit import audit_artifacts, audit_tree, run_audit  # noqa: E402


class ReleaseAuditTests(unittest.TestCase):
    def test_current_tree_is_clean(self):
        private_marker = "definitely-absent-" + "private-marker"
        report = run_audit(REPO_ROOT, private_terms=[private_marker])
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["creator_shadow_leakage"], 0)
        self.assertEqual(report["default_user_contamination_rate"], 0.0)

    def test_secret_value_is_reported_without_echoing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = "gh" + "p_" + "A" * 24
            (root / "config.txt").write_text(f"access_token = '{value}'\n", encoding="utf-8")
            report = audit_tree(root)
        self.assertTrue(report["findings"])
        self.assertNotIn(value, str(report))

    def test_private_profile_is_rejected_from_package(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "sample.whl"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("package/profile.json", "{}")
            report = audit_artifacts([artifact])
        self.assertEqual(report["findings"][0]["rule"], "private-package-member")


if __name__ == "__main__":
    unittest.main()
