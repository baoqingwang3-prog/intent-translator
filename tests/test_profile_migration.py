import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_profile import SCHEMA_VERSION, migrate_profile_file  # noqa: E402


class ProfileMigrationTests(unittest.TestCase):
    def test_legacy_profile_is_backed_up_and_private_values_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            legacy = {
                "schema_version": 0,
                "profile_id": "legacy-user",
                "language": "zh-CN",
                "phrase_mappings": {"my phrase": "my private meaning"},
                "study": {"goals": ["private goal"]},
            }
            original = json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
            path.write_text(original, encoding="utf-8")
            result = migrate_profile_file(path)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            backup = Path(result["backup"])
            self.assertTrue(result["changed"])
            self.assertEqual(result["from_version"], 0)
            self.assertEqual(result["to_version"], SCHEMA_VERSION)
            self.assertEqual(migrated["profile_id"], "legacy-user")
            self.assertEqual(migrated["phrase_mappings"]["my phrase"], "my private meaning")
            self.assertEqual(migrated["study"]["goals"], ["private goal"])
            self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_current_profile_is_idempotent_and_creates_no_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            profile = {
                "schema_version": SCHEMA_VERSION,
                "profile_id": "current",
                "language": "auto",
                "response_style": {"verbosity": "adaptive", "result_first": True},
                "autonomy": {"reversible_actions": "proceed", "high_impact_actions": "confirm"},
                "adaptation": {},
                "risk_policy": {"high_stakes": "verify"},
                "optional_adapters": {},
                "phrase_mappings": {},
                "memory": {"adapter": "sqlite", "location": "memory.db"},
            }
            path.write_text(json.dumps(profile), encoding="utf-8")
            result = migrate_profile_file(path)
            self.assertFalse(result["changed"])
            self.assertEqual(result["backup"], "")
            self.assertEqual(list(Path(temp).glob("*.bak-profile-*")), [])

    def test_current_profile_repairs_dangerous_short_confirmation_contains_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            profile = {
                "schema_version": SCHEMA_VERSION,
                "profile_id": "current-with-legacy-match",
                "language": "zh-CN",
                "response_style": {"verbosity": "adaptive", "result_first": True},
                "autonomy": {"reversible_actions": "proceed", "high_impact_actions": "confirm"},
                "adaptation": {},
                "risk_policy": {"high_stakes": "verify"},
                "optional_adapters": {},
                "phrase_mappings": {
                    "继续": {
                        "meaning": "继续当前尚未完成的流程",
                        "scope": "global",
                        "match_mode": "contains",
                        "confidence": "confirmed",
                    }
                },
                "memory": {"adapter": "sqlite", "location": "memory.db"},
            }
            path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

            result = migrate_profile_file(path)
            migrated = json.loads(path.read_text(encoding="utf-8"))

            self.assertTrue(result["changed"])
            self.assertEqual(result["safety_repairs"], 1)
            self.assertTrue(Path(result["backup"]).is_file())
            self.assertEqual(
                migrated["phrase_mappings"]["继续"]["meaning"],
                "继续当前尚未完成的流程",
            )
            self.assertEqual(migrated["phrase_mappings"]["继续"]["match_mode"], "exact")

    def test_future_profile_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            original = json.dumps({"schema_version": SCHEMA_VERSION + 1, "private": "keep"})
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "newer than supported"):
                migrate_profile_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(temp).glob("*.bak-profile-*")), [])


if __name__ == "__main__":
    unittest.main()
