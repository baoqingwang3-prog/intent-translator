from copy import deepcopy
from datetime import date
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_release_metadata import check_versions  # noqa: E402
from scripts.release_gate import (  # noqa: E402
    OFFICIAL_CAPABILITY_AUDIT,
    validate_official_capability_audit,
)


class ReleaseMetadataTests(unittest.TestCase):
    def test_versions_match(self):
        self.assertEqual(check_versions(), [])

    def test_matching_tag_passes(self):
        self.assertEqual(check_versions("v0.8.0a1"), [])

    def test_project_urls_point_to_public_repository(self):
        metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        repository = "https://github.com/baoqingwang3-prog/intent-translator"
        self.assertIn(f'Homepage = "{repository}"', metadata)
        self.assertIn(f'Repository = "{repository}"', metadata)
        self.assertIn(f'Issues = "{repository}/issues"', metadata)
        self.assertIn(f'Documentation = "{repository}/blob/main/README.md"', metadata)

    def test_official_capability_audit_is_current(self):
        self.assertEqual(
            validate_official_capability_audit(as_of=date(2026, 7, 28)),
            [],
        )

    def test_official_capability_audit_allows_one_day_timezone_skew(self):
        self.assertEqual(
            validate_official_capability_audit(as_of=date(2026, 7, 27)),
            [],
        )

    def test_official_capability_audit_rejects_stale_or_unofficial_sources(self):
        stale = deepcopy(OFFICIAL_CAPABILITY_AUDIT)
        stale["checked_at"] = "2026-01-01"
        self.assertIn(
            "official capability audit is stale",
            validate_official_capability_audit(stale, as_of=date(2026, 7, 28)),
        )
        unofficial = deepcopy(OFFICIAL_CAPABILITY_AUDIT)
        unofficial["hosts"]["codex"] = ["https://example.com/not-official"]
        self.assertTrue(
            any(
                "unofficial capability source" in error
                for error in validate_official_capability_audit(
                    unofficial, as_of=date(2026, 7, 28)
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
