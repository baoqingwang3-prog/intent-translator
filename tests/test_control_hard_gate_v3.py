"""Host controls for withdrawing an action or leaving its target unresolved."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import SemanticProposal  # noqa: E402


class FakeAdapter:
    name = "control-test"
    external = False

    def __init__(self, status):
        self.proposal = SemanticProposal.model_validate({
            "normalized_goal": "按用户原话处理",
            "mode": "change",
            "confidence": 0.9,
            "control_status": status,
        })

    def interpret(self, payload):
        return self.proposal


class HostControlGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intent-control-v3-")
        root = Path(self.temporary.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "control-v3",
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

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def compile(self, utterance, *, adapter=None, **kwargs):
        return IntentCompiler(registry={"skills": [], "errors": []}, semantic_adapter=adapter).compile(
            CompileRequest(utterance=utterance, semantic_mode="auto" if adapter else "off", **kwargs)
        )

    @staticmethod
    def active(result):
        return {item["predicate"] for item in result["intent_contract"]["actions"] if item["active_now"]}

    @staticmethod
    def prohibited(result):
        return {item["action"] for item in result["intent_contract"]["prohibitions"]}

    def assert_withdrawn(self, result, action):
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotIn(action, self.active(result))
        self.assertIn(action, self.prohibited(result))

    def test_postposed_stop_withdraws_pending_delete(self):
        result = self.compile(
            "缓存目录的删除任务到此停止，先保留目录。",
            pending_action="删除缓存目录",
        )
        self.assert_withdrawn(result, "delete")

    def test_colloquial_no_longer_send_withdraws_pending_transfer(self):
        result = self.compile(
            "先前说要把名单发给合作方，现在别传了。",
            pending_action="发送名单给合作方",
        )
        self.assert_withdrawn(result, "transfer")

    def test_postposed_withdrawal_blocks_pending_edit(self):
        result = self.compile(
            "之前要求改配置，这条要求撤回，原样放着。",
            pending_action="修改配置",
        )
        self.assert_withdrawn(result, "change")

    def test_withdrawal_preserves_separate_new_explanation(self):
        result = self.compile(
            "原定的发布通知先取消；请解释失败原因。",
            pending_action="发布通知",
        )
        self.assertIn(result["mode"], {"answer", "diagnose"})
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotIn("publish", self.active(result))
        self.assertIn("publish", self.prohibited(result))

    def test_pending_action_does_not_hide_multiple_context_targets(self):
        result = self.compile(
            "按刚才说的，把那份改成最终版。",
            context="有预算书甲和预算书乙两份，尚未决定处理哪份。",
            pending_action="修改预算书",
        )
        self.assertTrue(result["clarification_required"])
        self.assertIn("target_artifact", result["intent_contract"]["required_slots"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_named_context_target_is_not_abstained(self):
        result = self.compile(
            "把预算书甲改成最终版。",
            context="有预算书甲和预算书乙两份，尚未决定处理哪份。",
            pending_action="修改预算书",
        )
        self.assertNotIn("target_artifact", result["intent_contract"]["required_slots"])
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))

    def test_generic_permission_setting_needs_value(self):
        result = self.compile(
            "把团队成员权限统一修改成合适的。",
            pending_action="修改权限",
        )
        self.assertTrue(result["clarification_required"])
        self.assertIn("permission_setting", result["intent_contract"]["required_slots"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_explicit_permission_value_is_not_missing(self):
        result = self.compile(
            "把团队成员权限统一修改成只读。",
            pending_action="修改权限",
        )
        self.assertNotIn("permission_setting", result["intent_contract"]["required_slots"])
        self.assertEqual(result["intent_contract"]["effect"], "write_local")

    def test_semantic_control_can_veto_but_normal_cannot_cancel_local_veto(self):
        local = self.compile(
            "那次删除计划现在停止，数据先留着。",
            pending_action="删除数据",
            adapter=FakeAdapter("normal"),
        )
        self.assert_withdrawn(local, "delete")
        semantic = self.compile(
            "先处理一下之前那件事。",
            pending_action="删除数据",
            adapter=FakeAdapter("revoke"),
        )
        self.assert_withdrawn(semantic, "delete")

    def test_semantic_clarify_blocks_effect_and_frames(self):
        result = self.compile(
            "修改访问设置。",
            pending_action="修改访问设置",
            adapter=FakeAdapter("clarify"),
        )
        self.assertTrue(result["clarification_required"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])


if __name__ == "__main__":
    unittest.main()
