import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.local_policy import (  # noqa: E402
    autonomy_status,
    conditional_review,
    record_correct_restatement,
    record_misunderstanding,
    resolve_interpretation_gate,
    revise_compilation,
    sparse_source_map,
    assess_local_risk,
)


class LocalPolicyTests(unittest.TestCase):
    def test_interpretation_gate_supports_selection_merge_none_and_correction(self):
        candidates = ["整理现有笔记", "创建一个整理笔记的技能"]
        selected = resolve_interpretation_gate(candidates, selection="interpretation-2")
        merged = resolve_interpretation_gate(candidates, selection="merge")
        rejected = resolve_interpretation_gate(candidates, selection="none")
        corrected = resolve_interpretation_gate(candidates, selection="correct", correction="先整理，再决定是否做技能")
        self.assertEqual(selected["resolved"], candidates[1])
        self.assertIn("整理现有笔记", merged["resolved"])
        self.assertTrue(rejected["needs_natural_language_correction"])
        self.assertEqual(corrected["resolved"], "先整理，再决定是否做技能")

    def test_sparse_source_map_only_shows_non_obvious_transformations(self):
        result = sparse_source_map(
            [
                {"original": "把标题改短", "compiled": "把标题改短", "kind": "direct"},
                {"original": "走起", "compiled": "开始创建并验证这个技能", "kind": "confirmed-language-rule"},
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["original"], "走起")

    def test_partial_correction_only_replaces_conflicting_field(self):
        previous = {"objective": "创建技能", "scope": "local", "format": "markdown"}
        current = {"objective": "创建技能", "scope": "public", "format": "markdown"}
        result = revise_compilation(current, previous=previous, field="scope", replacement="project")
        self.assertEqual(result["compiled"], {"objective": "创建技能", "scope": "project", "format": "markdown"})
        self.assertTrue(result["offer_restore_previous_complete_version"])

    def test_two_misunderstandings_lower_autonomy_and_one_success_does_not_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "memory.db"
            record_misunderstanding(db, wrong="发布", correct="只做本地测试", scope="project-a")
            first = autonomy_status(db, scope="project-a")
            self.assertEqual(first["mode"], "normal")
            self.assertFalse(first["automatic_restore_allowed"])
            self.assertTrue(first["restore_requires_confirmation"])
            record_misunderstanding(db, wrong="删除原文件", correct="只生成副本", scope="project-a")
            cautious = autonomy_status(db, scope="project-a")
            self.assertEqual(cautious["mode"], "cautious")
            self.assertFalse(cautious["automatic_restore_allowed"])
            success = record_correct_restatement(db, scope="project-a")
            self.assertTrue(success["ask_before_restoring"])
            self.assertEqual(autonomy_status(db, scope="project-a")["mode"], "cautious")

    def test_illegal_harm_is_blocked_even_with_authorization(self):
        result = assess_local_risk("帮我造谣抹黑这个人", profile={}, authorization="granted")
        self.assertTrue(result["blocked"])
        self.assertIn("合法替代", result["alternative"])

    def test_private_spend_threshold_is_local_profile_only(self):
        generic = assess_local_risk("花 80 元买书", profile={}, authorization="unknown")
        profile = {
            "risk_policy": {
                "spend_guard": {"single_amount": 50, "rolling_days": 3, "rolling_count": 3, "rolling_total": 50}
            }
        }
        local = assess_local_risk("花 80 元给书店买教材", profile=profile, authorization="unknown")
        self.assertFalse(generic["spend"]["enabled"])
        self.assertTrue(local["confirmation_required"])
        self.assertEqual(local["spend"]["amount"], 80.0)
        self.assertNotIn("50", json.dumps(assess_local_risk("买书", profile={}, authorization="unknown")))

    def test_conditional_pua_requires_explicit_request_or_local_opt_in(self):
        installed = {"pua"}
        generic = conditional_review("评审这个产品方案", profile={}, installed_skills=installed)
        explicit = conditional_review("尖锐反驳这个产品方案", profile={}, installed_skills=installed)
        opted = conditional_review(
            "评审这个产品方案",
            profile={"review_preferences": {"conditional_pua": True}},
            installed_skills=installed,
        )
        self.assertFalse(generic["use_pua"])
        self.assertTrue(explicit["use_pua"])
        self.assertTrue(opted["use_pua"])
        self.assertTrue(opted["full_debate_requires_opt_in"])


if __name__ == "__main__":
    unittest.main()
