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
        self.assertEqual(check_versions("v0.6.0"), [])


if __name__ == "__main__":
    unittest.main()
