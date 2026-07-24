import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_profile import default_profile, set_phrase_mapping, validate_profile  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_default_profile_is_valid_and_contains_no_personal_phrase_mapping(self):
        profile = default_profile("zh-CN")
        self.assertEqual(validate_profile(profile), [])
        self.assertEqual(profile["phrase_mappings"], {})
        self.assertEqual(profile["memory"]["adapter"], "sqlite")
        self.assertEqual(profile["adaptation"]["expertise"], "adaptive")
        self.assertEqual(profile["risk_policy"]["high_stakes"], "verify")
        self.assertFalse(profile["optional_adapters"]["session_hooks"])
        self.assertFalse(profile["optional_adapters"]["reversible_context"])

    def test_invalid_adapter_is_rejected(self):
        profile = default_profile()
        profile["memory"]["adapter"] = "cloud-magic"
        errors = validate_profile(profile)
        self.assertTrue(any("memory.adapter" in error for error in errors))

    def test_invalid_adaptation_is_rejected(self):
        profile = default_profile()
        profile["adaptation"]["expertise"] = "mind-reader"
        errors = validate_profile(profile)
        self.assertTrue(any("adaptation.expertise" in error for error in errors))

    def test_confirmed_phrase_mapping_is_scoped_and_valid(self):
        profile = default_profile("zh-CN")
        mapping = set_phrase_mapping(
            profile,
            phrase="继续",
            meaning="Resume the current unfinished flow",
            scope="global",
        )
        self.assertEqual(mapping["confidence"], "confirmed")
        self.assertEqual(mapping["scope"], "global")
        self.assertEqual(validate_profile(profile), [])


if __name__ == "__main__":
    unittest.main()
