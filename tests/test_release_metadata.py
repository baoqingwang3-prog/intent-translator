import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_release_metadata import check_versions  # noqa: E402


class ReleaseMetadataTests(unittest.TestCase):
    def test_versions_match(self):
        self.assertEqual(check_versions(), [])

    def test_matching_tag_passes(self):
        self.assertEqual(check_versions("v0.7.1a2"), [])

    def test_project_urls_point_to_public_repository(self):
        metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        repository = "https://github.com/baoqingwang3-prog/intent-translator"
        self.assertIn(f'Homepage = "{repository}"', metadata)
        self.assertIn(f'Repository = "{repository}"', metadata)
        self.assertIn(f'Issues = "{repository}/issues"', metadata)
        self.assertIn(f'Documentation = "{repository}/blob/main/README.md"', metadata)


if __name__ == "__main__":
    unittest.main()
