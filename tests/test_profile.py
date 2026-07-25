import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_profile import (  # noqa: E402
    apply_profile_pack,
    configure_study_profile,
    default_profile,
    load_profile_pack,
    set_phrase_mapping,
    validate_profile,
)


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
        self.assertEqual(mapping["match_mode"], "exact")
        self.assertEqual(validate_profile(profile), [])

    def test_student_pack_is_generic_and_preserves_private_profile_fields(self):
        profile = default_profile("zh-CN")
        profile["phrase_mappings"]["继续"] = "Resume current work"
        memory_location = profile["memory"]["location"]
        packed = apply_profile_pack(profile, load_profile_pack("student-exam-prep"))
        self.assertTrue(packed["study"]["protect_study_time"])
        self.assertEqual(packed["study"]["goals"], [])
        self.assertEqual(packed["knowledge_pointers"]["vault_path"], "")
        self.assertEqual(packed["phrase_mappings"]["继续"], "Resume current work")
        self.assertEqual(packed["memory"]["location"], memory_location)
        self.assertEqual(validate_profile(packed), [])

    def test_university_pack_covers_general_student_life_without_private_values(self):
        packed = apply_profile_pack(default_profile("zh-CN"), load_profile_pack("university-student"))
        self.assertEqual(packed["student_life"]["role"], "university-student")
        self.assertIn("coursework", packed["student_life"]["areas"])
        self.assertIn("internships-and-career", packed["student_life"]["areas"])
        self.assertTrue(packed["student_state"]["enabled"])
        self.assertEqual(packed["student_state"]["authority"], "canonical-markdown")
        self.assertEqual(packed["study"]["goals"], [])
        self.assertEqual(packed["knowledge_pointers"]["vault_path"], "")
        self.assertEqual(validate_profile(packed), [])

    def test_local_study_configuration_overrides_only_private_fields(self):
        profile = apply_profile_pack(default_profile(), load_profile_pack("student-exam-prep"))
        configure_study_profile(
            profile,
            goals=["资格考试", "语言认证", "资格考试"],
            vault_name="测试",
            vault_path=str(REPO_ROOT),
            enable_shadow=True,
            shadow_preview_chars=48,
        )
        self.assertEqual(profile["study"]["goals"], ["资格考试", "语言认证"])
        self.assertEqual(profile["study"]["active_goal"], "资格考试")
        self.assertEqual(profile["knowledge_pointers"]["vault_name"], "测试")
        self.assertTrue(profile["shadow_evaluation"]["enabled"])
        self.assertFalse(profile["shadow_evaluation"]["notify_user"])
        self.assertEqual(profile["shadow_evaluation"]["preview_chars"], 48)
        self.assertEqual(validate_profile(profile), [])

    def test_profile_pack_numeric_settings_fail_validation_without_crashing(self):
        profile = apply_profile_pack(default_profile(), load_profile_pack("student-exam-prep"))
        profile["study"]["focus_window_minutes"] = "later"
        profile["shadow_evaluation"]["retention_days"] = False
        errors = validate_profile(profile)
        self.assertIn("study.focus_window_minutes must be positive", errors)
        self.assertIn("shadow_evaluation retention_days and max_events must be positive", errors)


if __name__ == "__main__":
    unittest.main()
