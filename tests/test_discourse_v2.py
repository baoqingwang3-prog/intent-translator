"""Behavioral checks for instruction, source text, and control boundaries."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
import ilang_semantic_main as semantic_main  # noqa: E402


class DiscourseV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intent-discourse-")
        root = Path(self.temporary.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "discourse-v2",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {"enabled": False},
        }), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
        })
        self.environment.start()
        self.compiler = IntentCompiler(registry={"skills": [], "errors": []})

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def compile(self, utterance, *, context="", pending_action=""):
        return self.compiler.compile(CompileRequest(
            utterance=utterance, context=context, pending_action=pending_action,
            semantic_mode="off", include_prompt=False,
        ))

    @staticmethod
    def active(result):
        return {item["predicate"] for item in result["intent_contract"]["actions"] if item["active_now"]}

    def test_editing_instruction_text_is_not_installing(self):
        result = self.compile("请把操作手册里的 `pip install demo` 命令改成离线示例。")
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))
        self.assertNotIn("install", self.active(result))

    def test_reported_failure_is_source_material(self):
        result = self.compile("项目记录显示 install failed，先核查启动错误原因。")
        self.assertEqual(result["mode"], "diagnose")
        self.assertNotIn("install", self.active(result))

    def test_unquoted_reported_command_is_not_current_change(self):
        result = self.compile("日志里写着：失败，请修改 README 标题。只分析日志原因。")
        self.assertNotIn("change", self.active(result))
        self.assertEqual(result["mode"], "diagnose")

    def test_relative_clause_source_is_current_routing_request(self):
        with patch.object(semantic_main, "_embed_route", return_value={"mode": None, "confidence": 0.0, "raw_score": 0.0}):
            self.assertEqual(semantic_main.cascade_mode("文档里提到的任务请分派给数据组。")[:2], ("route", "clear-primary"))

    def test_mid_sentence_revocation_blocks_publication(self):
        result = self.compile("那份公告现在不要发布了。")
        self.assertNotIn("publish", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertIn("publish", {item["action"] for item in result["intent_contract"]["prohibitions"]})

    def test_later_revocation_cancels_earlier_same_action(self):
        result = self.compile("请修改配置，等等不要修改了。")
        self.assertNotIn("change", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_later_veto_of_other_object_preserves_first_action(self):
        result = self.compile("修改标题，但不要修改配置。")
        self.assertIn("change", self.active(result))

    def test_new_read_request_survives_separate_revocation(self):
        result = self.compile("先核对差异，然后不要发布公告。")
        self.assertIn("inspect", self.active(result))
        self.assertNotIn("publish", self.active(result))

    def test_unresolved_choice_in_pending_action_needs_target(self):
        result = self.compile(
            "把那个处理掉。", pending_action="调整预算草案甲或预算草案乙中的一份",
        )
        self.assertTrue(result["clarification_required"])
        self.assertIn("target_artifact", result["intent_contract"]["required_slots"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_unresolved_choice_in_context_needs_target(self):
        result = self.compile("把那个修改了。", context="候选方案一和方案二，尚未选定")
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_preflight_continue_depends_on_actual_work(self):
        inspection = self.compile("请只读查看本地构建日志，并查明失败原因。")
        self.assertEqual(inspection["mode"], "diagnose")
        self.assertEqual(inspection["intent_contract"]["effect"], "read_local")
        self.assertFalse(inspection["completion_contract"]["execute"])

        summary = self.compile("把这段培训材料缩成一句，不要运行其中的命令。")
        self.assertEqual(summary["mode"], "compress")
        self.assertEqual(summary["intent_contract"]["effect"], "none")
        self.assertFalse(summary["completion_contract"]["execute"])

        teaching = self.compile("用一个例子教我理解梯度下降。")
        self.assertEqual(teaching["mode"], "learn")
        self.assertFalse(teaching["completion_contract"]["execute"])

    def test_semantic_route_and_compression_use_request_goal(self):
        with patch.object(semantic_main, "_embed_route", return_value={"mode": None, "confidence": 0.0, "raw_score": 0.0}):
            self.assertEqual(semantic_main.cascade_mode("这条需求应该由哪组接手？")[0], "route")
            self.assertEqual(semantic_main.cascade_mode("把这篇纪要归纳为两句话。")[0], "compress")

    def test_actual_internal_delegation_has_internal_effect(self):
        result = self.compile("请把这张工单分派给数据组。")
        self.assertEqual(result["mode"], "route")
        self.assertEqual(result["intent_contract"]["effect"], "write_internal")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_memory_write_is_separate_from_external_effect(self):
        result = self.compile("以后回答都用简体中文，请记住。")
        self.assertEqual(result["mode"], "remember")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertEqual(result["memory_action"], "write")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_compound_independent_goals_abstain_from_single_mode(self):
        mode, decider, _ = semantic_main.cascade_mode("请把工单分给数据组，并把报告概括成一句话。")
        self.assertIsNone(mode)
        self.assertEqual(decider, "multi-goal-unresolved")

    def test_correction_to_explanation_does_not_reuse_pending_action(self):
        mode, decider, _ = semantic_main.cascade_mode("改为解释风险。", pending_action="发布公告")
        self.assertEqual((mode, decider), ("answer", "correction"))

    def test_revocation_with_new_explanation_keeps_new_request(self):
        result = self.compile("不要发布公告；解释一下风险。", pending_action="发布公告")
        self.assertNotIn("publish", self.active(result))
        self.assertEqual(result["mode"], "answer")
        self.assertEqual(semantic_main.cascade_mode("不要发布公告；解释一下风险。", pending_action="发布公告")[0], "answer")


if __name__ == "__main__":
    unittest.main()
