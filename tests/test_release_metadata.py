import sys
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_release_metadata import check_versions  # noqa: E402


class ReleaseMetadataTests(unittest.TestCase):
    def test_versions_match(self):
        self.assertEqual(check_versions(), [])

    def test_matching_tag_passes(self):
        self.assertEqual(check_versions("v0.7.0a3"), [])

    def test_project_urls_point_to_public_repository(self):
        metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        urls = metadata["project"]["urls"]
        repository = "https://github.com/baoqingwang3-prog/intent-translator"
        self.assertEqual(urls["Homepage"], repository)
        self.assertEqual(urls["Repository"], repository)
        self.assertEqual(urls["Issues"], f"{repository}/issues")
        self.assertEqual(urls["Documentation"], f"{repository}/blob/main/README.md")


if __name__ == "__main__":
    unittest.main()
