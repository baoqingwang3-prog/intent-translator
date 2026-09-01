import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.server import intent_compile  # noqa: E402
from intent_translator_mcp.tool_gateway import decide_tool_access  # noqa: E402


class PrecheckRC4Tests(unittest.TestCase):
    def _assert_no_external_transfer_frame(self, contract: dict) -> None:
        self.assertNotIn("transfer", contract["active_actions"])
        self.assertNotIn("transfer", [item["predicate"] for item in contract["actions"]])
        self.assertFalse(
            any("external" in item.get("required_grants", []) for item in contract["actions"]),
            contract["actions"],
        )

    @contextmanager
    def _session(self):
        root = self._testMethodName
        profile = REPO_ROOT / ".rc4-test-profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": "precheck-rc4",
                    "phrase_mappings": {},
                    "memory": {"adapter": "none", "location": ""},
                    "study": {"enabled": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(REPO_ROOT / f".{root}.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(REPO_ROOT / f".{root}.state.db"),
            "INTENT_TRANSLATOR_SKILL_ROOTS": str(REPO_ROOT / "skills"),
        }
        try:
            with patch.dict(os.environ, env, clear=False):
                yield
        finally:
            for suffix in ("", ".db", ".state.db"):
                path = REPO_ROOT / (".rc4-test-profile.json" if not suffix else f".{root}{suffix}")
                if path.exists():
                    path.unlink()

    def _compile(self, utterance: str) -> dict:
        with self._session():
            return intent_compile(
                CompileRequest(
                    utterance=utterance,
                    semantic_mode="off",
                    include_prompt=False,
                    include_diagnostics=True,
                )
            )

    def test_request_ruling_is_nonexecuting_internal_answer(self):
        result = self._compile("请裁定这份方案是否可以交执行层；目前尚未交户部兵部")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "request_ruling_request")
        self.assertEqual(contract["operation"], "answer")
        self.assertEqual(contract["effect"], "none")
        self.assertEqual(contract["data_egress"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertEqual(result["tool_gateway"]["decision"], "allow")
        self.assertEqual(contract["active_actions"], [])
        self.assertIn("request_ruling_request", contract["mentioned_actions"])
        self.assertIn("route_internal_dispatch", contract["prohibited_actions"])
        self._assert_no_external_transfer_frame(contract)

    def test_rule_2_ruling_without_route_is_nonexecuting(self):
        utterances = [
            "请判断是否可以解除冻结；未获裁定前不启动任何执行动作。",
            "Ask the chief reviewer to decide whether the freeze may be lifted, while keeping all actions pending.",
        ]
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(utterance)
                contract = result["intent_contract"]
                self.assertEqual(contract["semantic_operation"], "request_ruling_request")
                self.assertEqual(contract["operation"], "answer")
                self.assertEqual(contract["effect"], "none")
                self.assertEqual(contract["data_egress"], "none")
                self.assertEqual(contract["actions"], [])
                self.assertEqual(contract["active_actions"], [])
                self.assertEqual(contract["required_grants"], [])
                self.assertFalse(contract["confirmation_required"])
                self.assertIsNone(result["risk"].get("confirmation_challenge"))
                self.assertFalse(result["completion_contract"]["execute"])
                self.assertEqual(result["tool_gateway"]["decision"], "allow")
                self.assertEqual(result["tool_gateway"]["route_call_count"], 0)
                self._assert_no_external_transfer_frame(contract)

    def test_internal_dispatch_projects_to_confirmed_internal_thread(self):
        result = self._compile("现在把已授权的总览发送到已确认的首辅 threadId=chief-1234。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "route_internal_dispatch")
        self.assertEqual(contract["operation"], "change")
        self.assertEqual(contract["effect"], "write_internal")
        self.assertEqual(contract["data_egress"], "none")
        self.assertEqual(contract["destination"]["kind"], "internal_thread")
        self.assertEqual(contract["destination"]["externality"], "internal")
        self.assertEqual(contract["destination"]["resolution"], "resolved")
        self.assertEqual(contract["destination"]["endpoint_ref"], "chief-1234")
        self.assertEqual(contract["required_grants"], [])
        self.assertTrue(result["completion_contract"]["execute"])
        self.assertEqual(result["tool_gateway"]["decision"], "allow")
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)
        self._assert_no_external_transfer_frame(contract)

        unresolved = self._compile("现在把已授权的总览发送到已确认的首辅 threadId。")
        unresolved_contract = unresolved["intent_contract"]
        self.assertEqual(unresolved_contract["semantic_operation"], "pending_route")
        self.assertEqual(unresolved_contract["destination"]["resolution"], "unresolved")
        self.assertEqual(unresolved_contract["destination"]["endpoint_ref"], "")
        self.assertIn("destination", unresolved_contract["required_slots"])
        self.assertFalse(unresolved["completion_contract"]["execute"])
        self.assertEqual(unresolved["tool_gateway"]["decision"], "human_review")
        self._assert_no_external_transfer_frame(unresolved_contract)

    def test_register_internal_thread_and_local_artifact_are_distinct(self):
        thread = self._compile("登记已确认的首辅 threadId 为内部会话。")
        thread_contract = thread["intent_contract"]
        self.assertEqual(thread_contract["semantic_operation"], "register_internal_thread")
        self.assertEqual(thread_contract["effect"], "write_internal")
        self.assertEqual(thread_contract["destination"]["kind"], "internal_thread")
        self.assertEqual(thread_contract["data_egress"], "none")
        self.assertEqual(thread_contract["required_grants"], [])
        self.assertNotEqual(thread_contract["semantic_operation"], "install")

        artifact = self._compile("登记这份本地 artifact 到本地清单，不上传。")
        artifact_contract = artifact["intent_contract"]
        self.assertEqual(artifact_contract["semantic_operation"], "register_local_artifact")
        self.assertEqual(artifact_contract["effect"], "write_local")
        self.assertEqual(artifact_contract["destination"]["kind"], "local_artifact")
        self.assertEqual(artifact_contract["data_egress"], "none")
        self.assertEqual(artifact_contract["required_grants"], [])
        self.assertNotEqual(artifact_contract["semantic_operation"], "publish_public")
        self.assertNotIn("register_local_artifact", artifact_contract["prohibited_actions"])

    def test_public_publish_is_external_and_waits_for_receipt(self):
        result = self._compile("把报告发布到 GitHub Pages 公网地址。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "publish_public")
        self.assertEqual(contract["operation"], "publish")
        self.assertEqual(contract["effect"], "write_external")
        self.assertEqual(contract["destination"]["kind"], "public_endpoint")
        self.assertEqual(contract["destination"]["externality"], "external")
        self.assertEqual(contract["data_egress"], "private_file")
        self.assertEqual(contract["required_grants"], ["external"])
        self.assertTrue(contract["confirmation_required"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotEqual(result["tool_gateway"]["decision"], "allow")
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)

    def test_int_gov_02_internal_review_prohibition_is_readonly(self):
        result = self._compile("仅汇总内部审议材料供首辅判断，不得下发给户部、兵部，尚未进入执行。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "report_status")
        self.assertEqual(contract["operation"], "answer")
        self.assertEqual(contract["effect"], "none")
        self.assertEqual(contract["data_egress"], "none")
        self.assertEqual(contract["destination"]["externality"], "internal")
        self.assertEqual(contract["required_grants"], [])
        self.assertFalse(contract["active_actions"])
        self.assertIn("route_internal_dispatch", contract["prohibited_actions"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)
        self._assert_no_external_transfer_frame(contract)
        self.assertEqual(contract["legacy_compatibility"]["destination"]["kind"], "local")
        self.assertEqual(contract["legacy_compatibility"]["data_egress"], "none")
        self.assertEqual(contract["legacy_compatibility"]["required_grants"], [])

        quoted_history = self._compile(
            "请整理内部报告，记录‘后续可能发布到 GitHub’这一历史计划；现在只交首辅审阅，不执行发布。"
        )
        quoted_contract = quoted_history["intent_contract"]
        self.assertEqual(quoted_contract["semantic_operation"], "report_status")
        self.assertEqual(quoted_contract["operation"], "answer")
        self.assertEqual(quoted_contract["effect"], "none")
        self.assertEqual(quoted_contract["data_egress"], "none")
        self.assertEqual(quoted_contract["required_grants"], [])
        self.assertFalse(quoted_history["completion_contract"]["execute"])
        self._assert_no_external_transfer_frame(quoted_contract)

    def test_pub_gh_02_public_report_requires_confirmation_challenge(self):
        result = self._compile("将公开测试报告发布到 GitHub Pages；真正对外写入前先请求确认。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "publish_public")
        self.assertEqual(contract["operation"], "publish")
        self.assertEqual(contract["effect"], "write_external")
        self.assertEqual(contract["destination"]["externality"], "external")
        self.assertEqual(contract["data_egress"], "private_file")
        self.assertEqual(contract["required_grants"], ["external"])
        self.assertTrue(contract["confirmation_required"])
        challenge = result["risk"].get("confirmation_challenge") or {}
        self.assertTrue(challenge.get("receipt"))
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotEqual(result["tool_gateway"]["decision"], "allow")
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)
        self.assertEqual([item["predicate"] for item in contract["actions"]], ["publish"])
        legacy = contract["legacy_compatibility"]
        self.assertEqual(legacy["destination"]["kind"], "external")
        self.assertEqual(legacy["data_egress"], "user_text")
        self.assertIn("external", legacy["required_grants"])
        self.assertIn("destructive", legacy["required_grants"])

    def test_meta_publication_prohibitions_stay_internal_readonly(self):
        utterances = [
            "评估报告未来是否适合发到 GitHub，但现在禁止发布，只写内部分析。",
            "提到公开发布只是风险说明；不要上传、推送或外发任何内容。",
            "讨论 GitHub 发布门槛，不代表现在执行发布，禁止实际推送。",
            "GitHub publication is mentioned as a risk scenario, not an instruction; prohibit upload and external transfer.",
            "只整理 GitHub 发布风险，禁止实际发布。",
            "未向任何执行机关下发，当前仅记录阻断条件。",
        ]
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(utterance)
                contract = result["intent_contract"]
                self.assertEqual(contract["semantic_operation"], "report_status")
                self.assertEqual(contract["operation"], "answer")
                self.assertEqual(contract["effect"], "none")
                self.assertEqual(contract["data_egress"], "none")
                self.assertEqual(contract["required_grants"], [])
                self.assertFalse(contract["confirmation_required"])
                self.assertFalse(result["completion_contract"]["execute"])
                self._assert_no_external_transfer_frame(contract)

    def test_meta_prohibition_does_not_activate_public_publish(self):
        result = self._compile("报告讨论发布风险，不要对外发布，尚未交执行层。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "report_status")
        self.assertEqual(contract["operation"], "answer")
        self.assertEqual(contract["effect"], "none")
        self.assertEqual(contract["data_egress"], "none")
        self.assertFalse(contract["active_actions"])
        self.assertIn("publish_public", contract["mentioned_actions"])
        self.assertIn("publish_public", contract["prohibited_actions"])
        self._assert_no_external_transfer_frame(contract)
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)

        post_negated = self._compile("总览会交执行层，后置结论：不得执行。")
        post_contract = post_negated["intent_contract"]
        self.assertEqual(post_contract["semantic_operation"], "report_status")
        self.assertIn("route_internal_dispatch", post_contract["prohibited_actions"])
        self.assertFalse(post_negated["completion_contract"]["execute"])
        self.assertEqual(post_negated["tool_gateway"]["route_call_count"], 0)
        self._assert_no_external_transfer_frame(post_contract)

    def test_pending_route_stays_unknown_and_gateway_fails_closed(self):
        result = self._compile("把总览交执行层。")
        contract = result["intent_contract"]
        self.assertEqual(contract["semantic_operation"], "pending_route")
        self.assertEqual(contract["operation"], "answer")
        self.assertEqual(contract["effect"], "none")
        self.assertEqual(contract["destination"]["kind"], "unknown")
        self.assertEqual(contract["destination"]["resolution"], "unresolved")
        self.assertEqual(contract["data_egress"], "none")
        self.assertIn("destination", contract["required_slots"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertEqual(result["tool_gateway"]["decision"], "human_review")
        self.assertEqual(result["tool_gateway"]["route_call_count"], 0)
        self._assert_no_external_transfer_frame(contract)

    def test_semantic_ids_are_stable_across_fresh_compiles(self):
        first = self._compile("请裁定这份方案是否可以交执行层；目前尚未交户部兵部。")
        second = self._compile("请裁定这份方案是否可以交执行层；目前尚未交户部兵部。")
        left = first["intent_contract"]
        right = second["intent_contract"]
        for field in ("semantic_id", "semantic_operation", "mentioned_actions", "active_actions", "prohibited_actions", "semantic_recipient", "routing_relation", "destination", "data_egress"):
            self.assertEqual(left[field], right[field], field)

    def test_gateway_rejects_typed_destination_egress_mismatch_without_route_call(self):
        result = decide_tool_access(
            operation="change",
            effect="write_internal",
            data_egress="public_query",
            risk={"blocked": False, "confirmation_required": False, "receipt_verified": False},
            clarification_required=False,
            semantic_operation="route_internal_dispatch",
            semantic_id="sem_test",
            semantic_recipient={"recipient_type": "internal_role", "relationship": "approver", "resolution": "resolved"},
            semantic_destination={"kind": "internal_thread", "externality": "internal", "resolution": "resolved"},
            authorized=True,
        )
        self.assertNotEqual(result["decision"], "allow")
        self.assertEqual(result["route_call_count"], 0)
        self.assertFalse(result["pre_dispatch_consistency"]["passed"])

        publish_mismatch = decide_tool_access(
            operation="publish",
            effect="write_external",
            data_egress="user_text",
            risk={"blocked": False, "confirmation_required": True, "receipt_verified": False},
            clarification_required=False,
            semantic_operation="publish_public",
            semantic_id="sem_publish_test",
            semantic_destination={"kind": "public_endpoint", "externality": "external", "resolution": "resolved"},
            authorized=False,
        )
        self.assertEqual(publish_mismatch["decision"], "deny")
        self.assertEqual(publish_mismatch["route_call_count"], 0)
        self.assertFalse(publish_mismatch["pre_dispatch_consistency"]["passed"])
        self.assertIn(
            "data_egress diverges from semantic truth",
            publish_mismatch["pre_dispatch_consistency"]["errors"],
        )


if __name__ == "__main__":
    unittest.main()
