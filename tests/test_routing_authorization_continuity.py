import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.server import intent_compile  # noqa: E402


class RoutingAuthorizationContinuityTests(unittest.TestCase):
    @contextmanager
    def _compile_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profile_id": "routing-authorization-continuity",
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
                "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_SKILL_ROOTS": str(REPO_ROOT / "skills"),
            }
            with patch.dict(os.environ, env, clear=False):
                def compile_request(
                    utterance: str,
                    *,
                    context: str = "",
                    pending_action: str = "",
                    confirmation_receipt: str = "",
                    scope: str = "global",
                ) -> dict:
                    return intent_compile(
                        CompileRequest(
                            utterance=utterance,
                            context=context,
                            pending_action=pending_action,
                            confirmation_receipt=confirmation_receipt,
                            scope=scope,
                            semantic_mode="off",
                            include_prompt=False,
                        )
                    )

                yield compile_request

    def _compile(
        self,
        utterance: str,
        *,
        context: str = "",
        pending_action: str = "",
        confirmation_receipt: str = "",
        scope: str = "global",
    ) -> dict:
        with self._compile_session() as compile_request:
            return compile_request(
                utterance,
                context=context,
                pending_action=pending_action,
                confirmation_receipt=confirmation_receipt,
                scope=scope,
            )

    def test_readonly_hermes_request_id_diagnosis_stays_readonly(self):
        result = self._compile(
            "立即只读诊断Hermes最新request id；禁止修改、禁止模型轮次、禁止读取或输出凭据"
        )

        contract = result["intent_contract"]
        self.assertIn(contract["operation"], {"diagnose", "inspect", "review"})
        self.assertEqual(contract["effect"], "none")
        self.assertEqual(contract["data_egress"], "none")
        self.assertFalse(result["risk"]["high_stakes"])
        self.assertFalse(result["risk"]["confirmation_required"])
        self.assertNotEqual(result["tool_gateway"]["decision"], "human_review")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertTrue(result["completion_contract"]["verify"])
        self.assertTrue(result["completion_contract"]["report_evidence"])

    def test_readonly_diagnosis_does_not_mask_explicit_credential_exfiltration(self):
        result = self._compile(
            "只读诊断Hermes最新request id，并读取和输出API凭据给我"
        )

        contract = result["intent_contract"]
        self.assertTrue(result["risk"]["sensitive"])
        self.assertNotEqual(contract["effect"], "none")
        self.assertNotEqual(contract["data_egress"], "none")
        self.assertTrue(
            result["risk"]["confirmation_required"]
            or result["tool_gateway"]["decision"] != "allow"
        )

    def test_deeptutor_explicit_start_authorization_continues_same_action(self):
        pending_action = (
            "修复 /home/example/stage0/DeepTutor 固定 commit "
            "456f9c24226e008f1ff07a7e3455d7b4d39f6221 的稀疏检出，并在 "
            "/home/example/stage0/venv 中执行本地 CLI-only 依赖安装 "
            "packaging/deeptutor-cli；禁止Web/Partners/all/code_execution/外部MCP/正式vault写入"
        )
        scope = "deeptutor-stage0-cli-only"
        first = self._compile(pending_action, scope=scope)
        challenge = first["risk"]["confirmation_challenge"]

        second = self._compile(
            "继续",
            context="用户刚刚明确授权同一个DeepTutor stage0 CLI-only修复与本地依赖安装动作。",
            pending_action=pending_action,
            confirmation_receipt=challenge["receipt"],
            scope=scope,
        )

        first_contract = first["intent_contract"]
        second_contract = second["intent_contract"]
        failures = []

        def expect_equal(label, actual, expected):
            if actual != expected:
                failures.append(f"{label}: actual={actual!r}, expected={expected!r}")

        expect_equal(
            "action_digest continuity",
            second["risk"]["receipt_status"].get("action_digest"),
            challenge["action_digest"],
        )
        expect_equal("object continuity", second_contract["object"]["value"], first_contract["object"]["value"])
        expect_equal("destination continuity", second_contract["destination"], first_contract["destination"])
        expect_equal("scope continuity", second_contract["scope"], first_contract["scope"])
        expect_equal("action_owner continuity", second_contract["action_owner"], first_contract["action_owner"])
        expect_equal("host action owner", second_contract["action_owner"]["kind"], "host")
        expect_equal("receipt verified", second_contract["authorization"]["receipt_verified"], True)
        expect_equal("execute authorized action", second["completion_contract"]["execute"], True)
        expect_equal("same confirmation not requested again", second["risk"]["confirmation_required"], False)
        expect_equal("no repeated confirmation challenge", "confirmation_challenge" in second["risk"], False)
        if second["routing"]["primary_skill"] in {"skill-installer", "obsidian-cli"}:
            failures.append(
                f"primary_skill drifted: actual={second['routing']['primary_skill']!r}, "
                "expected host/local system action"
            )
        expect_equal("pending action continuity", second_contract["pending_action"], pending_action)
        expect_equal("active task remains pending action", second_contract["active_task_source"], "pending")
        expect_equal("goal continuity", second_contract["goal"], first_contract["goal"])
        expect_equal("operation continuity", second_contract["operation"], first_contract["operation"])
        expect_equal("effect continuity", second_contract["effect"], first_contract["effect"])
        expect_equal("real action operation", second_contract["operation"], "install")
        expect_equal("real action effect", second_contract["effect"], "system_change")
        if "install" not in second_contract["authorization"]["required_grants"]:
            failures.append(
                "install grant missing from the authorized CLI-only dependency installation"
            )

        self.assertEqual(failures, [])

    def test_starting_installed_deeptutor_service_is_not_installation(self):
        result = self._compile(
            "启动已安装DeepTutor服务；禁止安装/升级/修改配置",
            scope="local-deeptutor-runtime",
        )

        contract = result["intent_contract"]
        failures = []
        if contract["operation"] == "install":
            failures.append("operation drifted to install")
        if result["routing"]["primary_skill"] in {"skill-installer", "obsidian-cli"}:
            failures.append(
                f"primary_skill drifted: actual={result['routing']['primary_skill']!r}"
            )
        self.assertEqual(failures, [])

    def test_deeptutor_readonly_monitor_not_blocked_by_install_confirmation(self):
        utterance = "只读检查DeepTutor stage0当前状态并报告证据，不做任何安装或修改"
        scope = "deeptutor-stage0-readonly-monitor"
        prior_install_context = (
            "此前DeepTutor CLI-only依赖安装已获得动作绑定授权，"
            "安装确认已完成，目前只等待后续状态检查；不得把旧安装动作作为当前动作。"
        )
        baseline = self._compile(utterance, scope=scope)
        result = self._compile(
            utterance,
            context=prior_install_context,
            scope=scope,
        )

        contract = result["intent_contract"]
        baseline_contract = baseline["intent_contract"]
        failures = []

        def expect_equal(label, actual, expected):
            if actual != expected:
                failures.append(f"{label}: actual={actual!r}, expected={expected!r}")

        if result["mode"] not in {"diagnose", "answer"}:
            failures.append(f"readonly mode: actual={result['mode']!r}")
        if contract["operation"] not in {"diagnose", "answer", "search", "test"}:
            failures.append(f"readonly operation: actual={contract['operation']!r}")
        if contract["effect"] not in {"none", "read_local"}:
            failures.append(f"readonly effect: actual={contract['effect']!r}")
        expect_equal("no data egress", contract["data_egress"], "none")
        if contract["operation"] == "install" or contract["effect"] == "system_change":
            failures.append(
                f"inherited install semantics: operation={contract['operation']!r}, "
                f"effect={contract['effect']!r}"
            )
        if "install" in contract["authorization"]["required_grants"]:
            failures.append("inherited install grant")
        expect_equal("no confirmation", result["risk"]["confirmation_required"], False)
        if result["tool_gateway"]["decision"] == "human_review":
            failures.append("readonly monitor was routed to human_review")
        if "confirmation_challenge" in result["risk"]:
            failures.append("readonly monitor generated an install confirmation challenge")
        if result["routing"]["primary_skill"] in {"skill-installer", "obsidian-cli"}:
            failures.append(
                f"primary_skill drifted: actual={result['routing']['primary_skill']!r}"
            )
        expect_equal("host action owner", contract["action_owner"]["kind"], "host")
        expect_equal("does not execute an install action", result["completion_contract"]["execute"], False)
        expect_equal("verify readonly evidence", result["completion_contract"]["verify"], True)
        expect_equal("report readonly evidence", result["completion_contract"]["report_evidence"], True)
        expect_equal("object unaffected by old install context", contract["object"], baseline_contract["object"])
        expect_equal("scope unaffected by old install context", contract["scope"], baseline_contract["scope"])
        expect_equal("operation unaffected by old install context", contract["operation"], baseline_contract["operation"])
        expect_equal("effect unaffected by old install context", contract["effect"], baseline_contract["effect"])
        expect_equal("owner unaffected by old install context", contract["action_owner"], baseline_contract["action_owner"])
        expect_equal(
            "current action does not inherit an install digest",
            result["risk"].get("receipt_status", {}).get("action_digest"),
            baseline["risk"].get("receipt_status", {}).get("action_digest"),
        )

        self.assertEqual(failures, [])

    def _assert_readonly_status_contract(self, result):
        contract = result["intent_contract"]
        failures = []
        if result["mode"] not in {"diagnose", "answer"}:
            failures.append(f"readonly mode: actual={result['mode']!r}")
        if contract["operation"] not in {"diagnose", "answer", "search", "test"}:
            failures.append(f"readonly operation: actual={contract['operation']!r}")
        if contract["effect"] not in {"none", "read_local"}:
            failures.append(f"readonly effect: actual={contract['effect']!r}")
        if contract["data_egress"] != "none":
            failures.append(f"data egress: actual={contract['data_egress']!r}")
        if "install" in contract["authorization"]["required_grants"]:
            failures.append("inherited install grant")
        if result["risk"]["confirmation_required"]:
            failures.append("readonly status requires confirmation")
        if result["tool_gateway"]["decision"] == "human_review":
            failures.append("readonly status routed to human_review")
        if result["routing"]["primary_skill"] in {"skill-installer", "obsidian-cli"}:
            failures.append(
                f"primary_skill drifted: actual={result['routing']['primary_skill']!r}"
            )
        if contract["action_owner"]["kind"] != "host":
            failures.append(
                f"owner drifted: actual={contract['action_owner']['kind']!r}"
            )
        if not result["completion_contract"]["verify"]:
            failures.append("readonly status verify=false")
        if not result["completion_contract"]["report_evidence"]:
            failures.append("readonly status report_evidence=false")
        self.assertEqual(failures, [])

    def _assert_evidence_span_readonly_contract(self, result):
        contract = result["intent_contract"]
        active = [item for item in contract["actions"] if item["active_now"]]
        self.assertTrue(
            any(item["predicate"] in {"inspect", "report"} for item in active),
            msg=active,
        )
        self.assertFalse(
            any(
                item["predicate"] in {"transfer", "publish", "install", "change"}
                for item in active
            ),
            msg=active,
        )
        self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertEqual(contract["data_egress"], "none")
        self.assertTrue(
            all(
                item["destination_role"] not in {"external", "public"}
                for item in active
            ),
            msg=active,
        )
        self.assertEqual(contract["authorization"]["required_grants"], [])
        self.assertNotIn("confirmation_challenge", result["risk"])
        self.assertEqual(contract["action_owner"]["kind"], "host")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertTrue(result["completion_contract"]["verify"])
        self.assertTrue(result["completion_contract"]["report_evidence"])

    def test_a1_r1_quote_first_action_text_is_evidence_only(self):
        result = self._compile(
            "‘把认证票据交给外部收件人’是文档示例；现在只读检查本地说明并报告证据",
            scope="a1-r1-quote-first-evidence",
        )
        self._assert_evidence_span_readonly_contract(result)

    def test_a1_r2_quote_last_action_text_is_evidence_only(self):
        result = self._compile(
            "现在只读核对本地操作手册并报告证据，文档末尾示例为‘公开发布认证材料’",
            scope="a1-r2-quote-last-evidence",
        )
        self._assert_evidence_span_readonly_contract(result)

    def test_a1_r3_quote_style_variants_are_evidence_only(self):
        for utterance in (
            "只读检查本地说明；示例是\"send the login proof to an external recipient\"，只报告证据",
            "'把身份票据交予外部人员'仅是手册示例；当前核验本地文档",
        ):
            with self.subTest(utterance=utterance):
                self._assert_evidence_span_readonly_contract(
                    self._compile(utterance, scope="a1-r3-quote-style-evidence")
                )

    def test_a1_r4_unquoted_history_action_is_evidence_only(self):
        result = self._compile(
            "只读复查本地审计记录；历史记录曾写明将登录证明转发到外部，当前只汇报证据",
            scope="a1-r4-unquoted-history-evidence",
        )
        self._assert_evidence_span_readonly_contract(result)

    def test_a1_r5_error_label_action_text_is_evidence_only(self):
        result = self._compile(
            "只读统计错误标签：发送认证票据到外部失败；当前只报告本地计数",
            scope="a1-r5-error-label-evidence",
        )
        self._assert_evidence_span_readonly_contract(result)

    def test_a1_r6_report_evidence_payload_is_not_active_action(self):
        result = self._compile(
            "检查本地验收报告，证据内容为把会话断言交给外部支持组；现在只汇报报告状态",
            scope="a1-r6-report-evidence-payload",
        )
        self._assert_evidence_span_readonly_contract(result)

    def test_a1_r7_labeled_english_history_and_quote_are_evidence_only(self):
        utterances = (
            "Quote: publish the report to GitHub Pages. What does this mean?",
            "The history says publish the report to GitHub Pages; summarize it.",
            "History: send the login proof to an external recipient. Explain this.",
        )
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(utterance, scope="a1-r7-labeled-evidence")
                contract = result["intent_contract"]
                self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
                self.assertIn(contract["effect"], {"none", "read_local"})
                self.assertEqual(contract["data_egress"], "none")
                self.assertFalse(
                    any(
                        item["predicate"] in {"transfer", "publish", "install", "change"}
                        and item["active_now"]
                        for item in contract["actions"]
                    ),
                    msg=contract["actions"],
                )
                self.assertEqual(contract["authorization"]["required_grants"], [])
                self.assertFalse(contract.get("confirmation_required", False))
                self.assertNotIn("confirmation_challenge", result["risk"])
                self.assertFalse(result["completion_contract"]["execute"])

    def test_a1_dir_active_quoted_target_remains_protected_transfer(self):
        result = self._compile(
            "现在把登录会话证明发送到外部目标‘夜间响应组’",
            scope="a1-dir-active-quoted-target",
        )
        contract = result["intent_contract"]
        active_transfer = [
            item
            for item in contract["actions"]
            if item["predicate"] == "transfer" and item["active_now"]
        ]
        self.assertEqual(len(active_transfer), 1, msg=contract["actions"])
        self.assertEqual(active_transfer[0]["destination_role"], "external")
        self.assertEqual(contract["operation"], "transfer")
        self.assertEqual(contract["effect"], "write_external")
        self.assertTrue(result["risk"]["sensitive"])
        self.assertEqual(
            set(contract["authorization"]["required_grants"]),
            {"external", "sensitive"},
        )
        self.assertNotEqual(result["tool_gateway"]["decision"], "allow")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_a1_canonical_identity_excludes_evidence_payload_but_keeps_quoted_target(self):
        evidence_a = self._compile(
            "文档示例为‘把认证票据交给外部甲组’，现在只读检查本地说明并报告证据",
            scope="a1-canonical-evidence-exclusion",
        )
        evidence_b = self._compile(
            "文档示例为‘把认证票据交给外部乙组’，现在只读检查本地说明并报告证据",
            scope="a1-canonical-evidence-exclusion",
        )
        self.assertEqual(
            evidence_a["intent_contract"]["authorization"]["canonical_action"],
            evidence_b["intent_contract"]["authorization"]["canonical_action"],
        )

        directive_a = self._compile(
            "现在把登录会话证明发送到外部目标‘甲组’",
            scope="a1-canonical-quoted-target",
        )
        directive_b = self._compile(
            "现在把登录会话证明发送到外部目标‘乙组’",
            scope="a1-canonical-quoted-target",
        )
        self.assertNotEqual(
            directive_a["intent_contract"]["authorization"]["canonical_action"],
            directive_b["intent_contract"]["authorization"]["canonical_action"],
        )
        for result in (directive_a, directive_b):
            self.assertEqual(
                set(result["intent_contract"]["authorization"]["required_grants"]),
                {"external", "sensitive"},
            )
            self.assertNotEqual(result["tool_gateway"]["decision"], "allow")
            self.assertFalse(result["completion_contract"]["execute"])

    def test_a1_receipt_identity_drift_rejects_without_consuming_original_receipt(self):
        original = "在本地 venv 安装 parser-lib 到本地工具目录"
        drift_cases = (
            ("predicate", "从本地 venv 删除 parser-lib 到本地工具目录", "a1-receipt-drift"),
            ("object", "在本地 venv 安装 different-lib 到本地工具目录", "a1-receipt-drift"),
            ("destination", "在本地 venv 安装 parser-lib 并发送到外部工单", "a1-receipt-drift"),
            ("scope", original, "a1-receipt-other-scope"),
        )
        for label, changed_action, changed_scope in drift_cases:
            with self.subTest(label=label), self._compile_session() as compile_request:
                first = compile_request(original, scope="a1-receipt-drift")
                receipt = first["risk"]["confirmation_challenge"]["receipt"]
                rejected = compile_request(
                    "继续",
                    pending_action=changed_action,
                    confirmation_receipt=receipt,
                    scope=changed_scope,
                )
                accepted = compile_request(
                    "继续",
                    pending_action=original,
                    confirmation_receipt=receipt,
                    scope="a1-receipt-drift",
                )
            self.assertFalse(rejected["risk"]["receipt_verified"], msg=label)
            self.assertFalse(rejected["completion_contract"]["execute"], msg=label)
            self.assertFalse(
                rejected["risk"].get("receipt_status", {}).get("consumed", False),
                msg=label,
            )
            self.assertTrue(accepted["risk"]["receipt_verified"], msg=label)
            self.assertTrue(accepted["completion_contract"]["execute"], msg=label)

    def test_readonly_monitor_with_do_not_execute_install_is_not_install(self):
        result = self._compile(
            "只读监控DeepTutor安装会话的当前退出状态，不执行安装、不修改文件",
            scope="deeptutor-install-session-readonly-monitor",
        )
        self._assert_readonly_status_contract(result)

    def test_view_installed_service_status_with_no_install_is_readonly(self):
        result = self._compile(
            "查看已安装DeepTutor服务状态；不要安装、升级或更改配置",
            scope="deeptutor-installed-service-readonly-status",
        )
        self._assert_readonly_status_contract(result)

    def test_english_readonly_status_without_install_reports_evidence(self):
        result = self._compile(
            "Read-only check the DeepTutor stage0 status and report evidence "
            "without installing, upgrading, or modifying anything",
            scope="deeptutor-stage0-readonly-monitor",
        )
        self._assert_readonly_status_contract(result)

    def test_mixed_language_readonly_inspect_with_negated_install_is_readonly(self):
        result = self._compile(
            "只读 inspect DeepTutor 的运行情况，禁止 install 或改配置",
            scope="deeptutor-runtime-readonly-inspection",
        )
        self._assert_readonly_status_contract(result)

    def test_later_confirmed_install_overrides_initial_readonly_check(self):
        result = self._compile(
            "先只读检查服务状态，不要改配置；确认后安装更新",
            scope="deeptutor-confirmed-update-install",
        )

        contract = result["intent_contract"]
        failures = []
        if result["mode"] != "diagnose":
            failures.append(f"readonly mode: actual={result['mode']!r}")
        if contract["operation"] != "diagnose":
            failures.append(f"readonly operation: actual={contract['operation']!r}")
        if contract["effect"] != "none":
            failures.append(f"readonly effect: actual={contract['effect']!r}")
        if contract["authorization"]["required_grants"]:
            failures.append(
                "current grants are not empty: "
                f"actual={contract['authorization']['required_grants']!r}"
            )
        if result["risk"]["confirmation_required"]:
            failures.append("conditional branch triggered current confirmation")
        if result["risk"].get("confirmation_challenge"):
            failures.append("conditional branch triggered current challenge")
        if "confirmation_challenge" in result["risk"]:
            failures.append("current risk contains a confirmation challenge field")
        if "action_digest" in result["risk"]:
            failures.append("conditional install leaked into current risk action digest")
        if contract["authorization"]["action_digest"] != "":
            failures.append(
                "current authorization action digest is not empty: "
                f"actual={contract['authorization']['action_digest']!r}"
            )
        if contract["authorization"]["receipt_verified"]:
            failures.append("conditional install reported a verified receipt")
        if result["risk"].get("receipt_status", {}).get("consumed"):
            failures.append("conditional install consumed a receipt")
        if result["tool_gateway"]["decision"] != "allow":
            failures.append(
                f"readonly gateway: actual={result['tool_gateway']['decision']!r}"
            )
        completion = result["completion_contract"]
        if completion["execute"]:
            failures.append("conditional install executes before activation")
        if not completion["verify"]:
            failures.append("readonly inspect verify=false")
        if not completion["report_evidence"]:
            failures.append("readonly inspect report_evidence=false")

        active_actions = [item for item in contract["actions"] if item["active_now"]]
        if len(active_actions) != 1:
            failures.append(f"active action count: actual={len(active_actions)}")
        else:
            active = active_actions[0]
            expected_active = {
                "predicate": "inspect",
                "polarity": "asserted",
                "temporal_role": "current",
                "gate_state": "active",
                "required_grants": [],
                "confirmation_challenge": None,
            }
            for field, expected in expected_active.items():
                if active[field] != expected:
                    failures.append(
                        f"active inspect {field}: actual={active[field]!r}"
                    )

        if len(contract["branches"]) != 1:
            failures.append(f"conditional branch count: actual={len(contract['branches'])}")
        else:
            branch = contract["branches"][0]
            expected_branch = {
                "predicate": "install",
                "polarity": "asserted",
                "temporal_role": "conditional",
                "active_now": False,
                "gate_state": "dormant",
                "required_grants": ["install"],
                "confirmation_challenge": None,
            }
            for field, expected in expected_branch.items():
                if branch[field] != expected:
                    failures.append(
                        f"conditional install {field}: actual={branch[field]!r}"
                    )
            if not branch["canonical_args"]:
                failures.append("conditional install canonical_args missing")
            if not branch["per_frame_digest"]:
                failures.append("conditional install per_frame_digest missing")
            expected_artifact = {
                "predicate": "install",
                "object": branch["object"],
                "destination": branch["destination_role"],
                "scope": "deeptutor-confirmed-update-install",
                "temporal_role": "conditional",
            }
            if branch["canonical_args"] != expected_artifact:
                failures.append(
                    "conditional install canonical_args mismatch: "
                    f"actual={branch['canonical_args']!r}"
                )
            if branch["bundle_digest"]:
                failures.append("conditional install entered current active bundle")
        self.assertEqual(failures, [])

    def test_colloquial_readonly_evidence_with_negated_upgrade_is_readonly(self):
        result = self._compile(
            "核对本地 DeepTutor 是否正常运行，只给我证据，千万别升级或动配置",
            scope="deeptutor-local-runtime-evidence-check",
        )
        self._assert_readonly_status_contract(result)

    def test_local_log_request_id_lookup_does_not_route_to_public_search(self):
        result = self._compile(
            "查一下最新 Hermes 500 对应的 request id，只看日志并汇报，"
            "任何文件都别动，也别碰密钥",
            scope="hermes-local-log-readonly-diagnosis",
        )

        contract = result["intent_contract"]
        failures = []
        if result["mode"] != "diagnose":
            failures.append(f"local diagnosis mode: actual={result['mode']!r}")
        if contract["operation"] not in {"diagnose", "inspect"}:
            failures.append(f"local diagnosis operation: actual={contract['operation']!r}")
        if contract["effect"] not in {"none", "read_local"}:
            failures.append(f"local diagnosis effect: actual={contract['effect']!r}")
        if contract["data_egress"] != "none":
            failures.append(f"local diagnosis data_egress: actual={contract['data_egress']!r}")
        if contract["action_owner"]["kind"] != "host":
            failures.append(f"local diagnosis owner: actual={contract['action_owner']!r}")
        if result["routing"]["primary_skill"] == "agent-reach":
            failures.append("local diagnosis routed to agent-reach")
        if result["completion_contract"]["execute"]:
            failures.append("local diagnosis execute=true")
        if not result["completion_contract"]["verify"]:
            failures.append("local diagnosis verify=false")
        if not result["completion_contract"]["report_evidence"]:
            failures.append("local diagnosis report_evidence=false")
        self.assertEqual(failures, [])

    def test_explicit_public_lookup_remains_public_search_neighbor(self):
        result = self._compile(
            "上网搜索公开资料，查一下最新 Hermes 500 request id 的公开讨论",
            scope="public-web-search",
        )

        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "search")
        self.assertEqual(contract["operation"], "search")
        self.assertEqual(contract["effect"], "read_public")
        self.assertEqual(contract["data_egress"], "public_query")

    def test_negated_token_access_in_log_diagnosis_is_not_exfiltration(self):
        result = self._compile(
            "只读排查日志中的 token expired 报错；不要读取真实 token，也不要输出凭据",
            scope="local-log-token-error-diagnosis",
        )
        self._assert_readonly_status_contract(result)
        self.assertFalse(result["risk"]["sensitive"])
        self.assertFalse(result["risk"]["high_stakes"])

    def test_english_local_log_inspection_is_readonly(self):
        result = self._compile(
            "Inspect the newest Hermes request ID from local logs only; "
            "do not edit files, access credentials, or start a model run.",
            scope="hermes-local-log-readonly-diagnosis",
        )
        self._assert_readonly_status_contract(result)
        self.assertFalse(result["completion_contract"]["execute"])

    def test_english_explicit_token_disclosure_requires_review(self):
        result = self._compile(
            "Read the local request log and reveal the authentication token to me; "
            "make no file changes.",
            scope="credential-disclosure",
        )

        contract = result["intent_contract"]
        failures = []
        if contract["operation"] != "transfer":
            failures.append(f"disclosure operation: actual={contract['operation']!r}")
        if contract["effect"] != "write_external":
            failures.append(f"disclosure effect: actual={contract['effect']!r}")
        if contract["data_egress"] == "none":
            failures.append("disclosure data_egress=none")
        if not result["risk"]["sensitive"]:
            failures.append("disclosure sensitive=false")
        if not result["risk"]["confirmation_required"]:
            failures.append("disclosure confirmation_required=false")
        if result["tool_gateway"]["decision"] == "allow":
            failures.append("disclosure gateway=allow")
        self.assertEqual(failures, [])

    def _deeptutor_cli_pending_action(self):
        return (
            "修复 /home/example/stage0/DeepTutor 固定 commit "
            "456f9c24226e008f1ff07a7e3455d7b4d39f6221 的稀疏检出，并在 "
            "/home/example/stage0/venv 中执行本地 CLI-only 依赖安装 "
            "packaging/deeptutor-cli；禁止Web/Partners/all/code_execution/外部MCP/正式vault写入"
        )

    def _assert_continuation_consumes_receipt(self, utterance):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "deeptutor-stage0-cli-only"
        with self._compile_session() as compile_request:
            first = compile_request(pending_action, scope=scope)
            challenge = first["risk"]["confirmation_challenge"]
            second = compile_request(
                utterance,
                context="上一轮等待确认同一个DeepTutor stage0 CLI-only本地依赖安装动作。",
                pending_action=pending_action,
                confirmation_receipt=challenge["receipt"],
                scope=scope,
            )

        contract = second["intent_contract"]
        failures = []
        status = second["risk"].get("receipt_status", {})
        if not status.get("verified"):
            failures.append(f"receipt not verified: reason={status.get('reason')!r}")
        if status.get("action_digest") != challenge["action_digest"]:
            failures.append(
                f"receipt digest: actual={status.get('action_digest')!r}, "
                f"expected={challenge['action_digest']!r}"
            )
        if not contract["authorization"]["receipt_verified"]:
            failures.append("authorization receipt_verified=false")
        if not second["completion_contract"]["execute"]:
            failures.append("continuation execute=false")
        if second["risk"]["confirmation_required"]:
            failures.append("continuation requested duplicate confirmation")
        if "confirmation_challenge" in second["risk"]:
            failures.append("continuation emitted duplicate challenge")
        if contract["pending_action"] != pending_action:
            failures.append(f"pending action drift: actual={contract['pending_action']!r}")
        if contract["active_task_source"] != "pending":
            failures.append(f"active task source: actual={contract['active_task_source']!r}")
        if contract["operation"] != "install" or contract["effect"] != "system_change":
            failures.append(
                f"action drift: operation={contract['operation']!r}, effect={contract['effect']!r}"
            )
        self.assertEqual(failures, [])

    def test_natural_confirmation_can_continue_and_consume_same_receipt(self):
        self._assert_continuation_consumes_receipt("可以，继续")

    def test_colloquial_continuation_can_continue_and_consume_same_receipt(self):
        self._assert_continuation_consumes_receipt("接着来")

    def test_negated_obsidian_boundary_does_not_steal_local_install_owner(self):
        result = self._compile(
            "在本地 venv 安装 deeptutor-cli，禁止写入 Obsidian vault",
            scope="local-venv-cli-install",
        )

        contract = result["intent_contract"]
        failures = []
        if contract["operation"] != "install":
            failures.append(f"local install operation: actual={contract['operation']!r}")
        if contract["effect"] != "system_change":
            failures.append(f"local install effect: actual={contract['effect']!r}")
        if contract["action_owner"]["kind"] != "host":
            failures.append(f"local install owner: actual={contract['action_owner']!r}")
        if result["routing"]["primary_skill"] is not None:
            failures.append(f"local install primary_skill: actual={result['routing']['primary_skill']!r}")
        if "install" not in contract["authorization"]["required_grants"]:
            failures.append("local install grant missing")
        if not result["risk"]["confirmation_required"]:
            failures.append("local install confirmation_required=false")
        self.assertEqual(failures, [])

    def test_starting_installed_service_remains_executable_in_chinese_and_english(self):
        utterances = (
            "把已经装好的 DeepTutor 服务跑起来，只检查本地健康状态，不要安装任何包",
            "Start the already installed DeepTutor service and only check local health; "
            "do not install any packages.",
        )
        failures = []
        for utterance in utterances:
            result = self._compile(utterance, scope="local-installed-service-start")
            contract = result["intent_contract"]
            label = utterance[:24]
            if result["mode"] != "change":
                failures.append(f"{label} mode: actual={result['mode']!r}")
            if contract["operation"] != "start":
                failures.append(f"{label} operation: actual={contract['operation']!r}")
            if contract["effect"] != "write_local":
                failures.append(f"{label} effect: actual={contract['effect']!r}")
            if contract["action_owner"]["kind"] != "host":
                failures.append(f"{label} owner: actual={contract['action_owner']!r}")
            if not result["completion_contract"]["execute"]:
                failures.append(f"{label} execute=false")
            if contract["operation"] == "install":
                failures.append(f"{label} operation drifted to install")
            if "install" in contract["authorization"]["required_grants"]:
                failures.append(f"{label} inherited install grant")
            if result["routing"]["primary_skill"] in {"skill-installer", "obsidian-cli"}:
                failures.append(
                    f"{label} primary_skill: actual={result['routing']['primary_skill']!r}"
                )
        self.assertEqual(failures, [])

    def test_parallel_readonly_prohibitions_are_all_preserved_without_stealing_owner(self):
        result = self._compile(
            "请只读验收当前任务；不要修改文件，不要启动浏览器，不要安装软件，"
            "不要向外发送数据，只报告证据",
            scope="current-task-readonly-acceptance",
        )

        contract = result["intent_contract"]
        prohibition_text = " ".join(
            item.get("text", "")
            for item in contract.get("prohibitions", contract.get("constraints", []))
        )
        failures = []
        for expected in (
            "不要修改文件",
            "不要启动浏览器",
            "不要安装软件",
            "不要向外发送数据",
        ):
            if expected not in prohibition_text:
                failures.append(f"missing prohibition: {expected}")
        if contract["action_owner"]["kind"] != "host":
            failures.append(f"owner stolen by prohibition: actual={contract['action_owner']!r}")
        if result["routing"]["primary_skill"] is not None:
            failures.append(
                f"skill route stolen by prohibition: actual={result['routing']['primary_skill']!r}"
            )
        if result["mode"] != "diagnose" or contract["operation"] != "diagnose":
            failures.append(
                f"readonly classification: mode={result['mode']!r}, "
                f"operation={contract['operation']!r}"
            )
        if contract["effect"] != "none":
            failures.append(f"readonly effect: actual={contract['effect']!r}")
        if result["risk"]["confirmation_required"]:
            failures.append("readonly acceptance requires confirmation")
        if not result["completion_contract"]["verify"]:
            failures.append("readonly acceptance verify=false")
        if not result["completion_contract"]["report_evidence"]:
            failures.append("readonly acceptance report_evidence=false")
        self.assertEqual(failures, [])

    def test_semantic_authentication_material_disclosure_is_protected_transfer(self):
        result = self._compile(
            "读取本地登录材料，并复制到外部工单里给对方",
            scope="authentication-material-external-disclosure",
        )
        contract = result["intent_contract"]
        self.assertEqual(contract["operation"], "transfer")
        self.assertEqual(contract["effect"], "write_external")
        self.assertTrue(result["risk"]["sensitive"])
        self.assertTrue(result["risk"]["confirmation_required"])
        self.assertNotEqual(result["tool_gateway"]["decision"], "allow")

    def test_negated_authentication_material_disclosure_remains_readonly(self):
        result = self._compile(
            "只读核验本地登录材料是否存在，不要复制或补到任何外部系统，只报告证据",
            scope="authentication-material-readonly-check",
        )
        self._assert_readonly_status_contract(result)
        self.assertFalse(result["risk"]["sensitive"])

    def test_auth_capability_disclosure_triplet_uses_frame_roles(self):
        original = self._compile(
            "读取本地单点登录会话串，并附入外部支持票据",
            scope="auth-capability-disclosure-triplet",
        )
        contract = original["intent_contract"]
        self.assertEqual(contract["operation"], "transfer")
        self.assertEqual(contract["effect"], "write_external")
        self.assertEqual(
            set(contract["authorization"]["required_grants"]),
            {"external", "sensitive"},
        )
        self.assertTrue(original["risk"]["sensitive"])
        self.assertEqual(original["tool_gateway"]["decision"], "human_review")
        self.assertFalse(original["completion_contract"]["execute"])
        transfer_frames = [
            item
            for item in contract["actions"]
            if item["predicate"] == "transfer" and item["polarity"] == "asserted"
        ]
        self.assertEqual(len(transfer_frames), 1)
        self.assertIn("外部支持票据", transfer_frames[0]["object"])
        self.assertEqual(
            set(transfer_frames[0]["required_grants"]),
            {"external", "sensitive"},
        )

        negated = self._compile(
            "只读核验本地单点登录会话串是否存在，不要附入外部支持票据，只报告证据",
            scope="auth-capability-disclosure-triplet",
        )
        self._assert_readonly_status_contract(negated)
        self.assertFalse(negated["risk"]["sensitive"])
        prohibited = [
            item
            for item in negated["intent_contract"]["actions"]
            if item["polarity"] == "prohibited"
        ]
        self.assertTrue(any(item["predicate"] == "transfer" for item in prohibited))

        label_only = self._compile(
            "只读核对错误标签‘登录票据缺失’的数量，只报告证据",
            scope="auth-capability-label-only",
        )
        self._assert_readonly_status_contract(label_only)
        self.assertFalse(label_only["risk"]["sensitive"])

    def test_implicit_auth_transfer_predicates_are_protected(self):
        utterances = (
            "Hand the local SSO session assertion to an external support agent.",
            "Provide the local login session value to the external incident ticket.",
            "Carry the local authentication session string into the external support chat.",
            "Give the local sign-in session material to the outside recipient.",
        )
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(
                    utterance,
                    scope="implicit-auth-transfer-predicates",
                )
                contract = result["intent_contract"]
                transfer_frames = [
                    item
                    for item in contract["actions"]
                    if item["predicate"] == "transfer"
                    and item["polarity"] == "asserted"
                ]
                self.assertEqual(len(transfer_frames), 1)
                self.assertEqual(contract["operation"], "transfer")
                self.assertEqual(contract["effect"], "write_external")
                self.assertEqual(
                    set(transfer_frames[0]["required_grants"]),
                    {"external", "sensitive"},
                )
                self.assertEqual(
                    set(contract["authorization"]["required_grants"]),
                    {"external", "sensitive"},
                )
                self.assertTrue(result["risk"]["sensitive"])
                self.assertEqual(result["tool_gateway"]["decision"], "human_review")
                self.assertFalse(result["completion_contract"]["execute"])

    def test_negated_transfer_then_comma_readonly_clause_has_separate_polarity(self):
        result = self._compile(
            "不要把本地登录会话串交给外部支持人员，只读检查本地错误记录并报告证据",
            scope="negated-transfer-followed-by-readonly-clause",
        )
        contract = result["intent_contract"]
        prohibited = [
            item
            for item in contract["actions"]
            if item["polarity"] == "prohibited"
        ]
        active = [item for item in contract["actions"] if item["active_now"]]
        self.assertTrue(any(item["predicate"] == "transfer" for item in prohibited))
        self.assertTrue(
            any(
                item["predicate"] in {"inspect", "report"}
                and item["polarity"] == "asserted"
                for item in active
            )
        )
        self._assert_readonly_status_contract(result)
        self.assertFalse(result["risk"]["sensitive"])
        self.assertEqual(contract["authorization"]["required_grants"], [])
        self.assertNotIn("confirmation_challenge", result["risk"])

    def test_bounded_ba_sensitive_capability_to_external_recipient_is_transfer(self):
        result = self._compile(
            "把本地登录会话值给外部响应人员",
            scope="bounded-ba-sensitive-transfer",
        )
        contract = result["intent_contract"]
        active_transfer = [
            item
            for item in contract["actions"]
            if item["predicate"] == "transfer"
            and item["polarity"] == "asserted"
            and item["active_now"]
        ]
        self.assertEqual(len(active_transfer), 1)
        self.assertEqual(contract["operation"], "transfer")
        self.assertEqual(contract["effect"], "write_external")
        self.assertEqual(
            set(contract["authorization"]["required_grants"]),
            {"external", "sensitive"},
        )
        self.assertTrue(result["risk"]["sensitive"])
        self.assertEqual(result["tool_gateway"]["decision"], "human_review")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_sensitive_transfer_role_matrix_handles_bounded_delivery_synonyms(self):
        utterances = (
            "将用于单点登录的临时会话断言转交至外部轮值组",
            "把认证会话字符串转发到外部支持工单",
            "将这段可直接登录的访问材料递送至外部响应方",
            "把外部值班员需要的身份验证票据委托其接收",
        )
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(utterance, scope="sensitive-transfer-role-matrix")
                contract = result["intent_contract"]
                active_transfer = [
                    item
                    for item in contract["actions"]
                    if item["predicate"] == "transfer"
                    and item["polarity"] == "asserted"
                    and item["active_now"]
                ]
                self.assertEqual(len(active_transfer), 1, msg=contract["actions"])
                self.assertEqual(contract["operation"], "transfer")
                self.assertEqual(contract["effect"], "write_external")
                self.assertEqual(
                    set(contract["authorization"]["required_grants"]),
                    {"external", "sensitive"},
                )
                self.assertTrue(result["risk"]["sensitive"])
                self.assertEqual(result["tool_gateway"]["decision"], "human_review")
                self.assertFalse(result["completion_contract"]["execute"])

    def test_transfer_frames_are_quote_aware_and_deduplicated_by_clause_role(self):
        positive = self._compile(
            "把登录会话证明转交给外部支持人员",
            scope="transfer-frame-role-dedup-positive",
        )
        positive_active = [
            item
            for item in positive["intent_contract"]["actions"]
            if item["predicate"] == "transfer" and item["active_now"]
        ]
        self.assertEqual(len(positive_active), 1, msg=positive["intent_contract"]["actions"])

        negated = self._compile(
            "不要把登录会话证明转交给外部支持人员，只读检查本地记录并报告证据",
            scope="transfer-frame-role-dedup-negated",
        )
        prohibited = [
            item
            for item in negated["intent_contract"]["actions"]
            if item["predicate"] == "transfer" and item["polarity"] == "prohibited"
        ]
        negated_active = [
            item
            for item in negated["intent_contract"]["actions"]
            if item["predicate"] == "transfer" and item["active_now"]
        ]
        self.assertEqual(len(prohibited), 1, msg=negated["intent_contract"]["actions"])
        self.assertEqual(negated_active, [])

        historical = self._compile(
            "只读核对历史记录：‘将登录会话证明转交给外部人员’是旧工单文字；现在只报告本地证据",
            scope="transfer-frame-quoted-history",
        )
        historical_contract = historical["intent_contract"]
        historical_active = [item for item in historical_contract["actions"] if item["active_now"]]
        self.assertFalse(any(item["predicate"] == "transfer" for item in historical_active))
        self.assertTrue(
            all(
                item["destination_role"] != "external"
                for item in historical_active
                if item["predicate"] in {"inspect", "report"}
            ),
            msg=historical_active,
        )
        self.assertFalse(historical["risk"]["sensitive"])
        self.assertEqual(historical_contract["authorization"]["required_grants"], [])
        self.assertNotIn("confirmation_challenge", historical["risk"])

        document_quote = self._compile(
            "只读检查本地说明文档，其中写着‘将登录会话证明转交给外部接收方’，只报告文档证据",
            scope="transfer-frame-document-quote-destination",
        )
        document_contract = document_quote["intent_contract"]
        document_active = [
            item for item in document_contract["actions"] if item["active_now"]
        ]
        self.assertFalse(any(item["predicate"] == "transfer" for item in document_active))
        self.assertTrue(
            all(
                item["destination_role"] in {"local", "unknown"}
                for item in document_active
                if item["predicate"] in {"inspect", "report"}
            ),
            msg=document_active,
        )
        self.assertFalse(document_quote["risk"]["sensitive"])
        self.assertEqual(document_contract["authorization"]["required_grants"], [])
        self.assertNotIn("confirmation_challenge", document_quote["risk"])

    def test_generic_session_proof_is_sensitive_when_asserted_to_external_recipient(self):
        result = self._compile(
            "将本地会话证明递送给外部响应方",
            scope="generic-session-proof-sensitive-transfer",
        )
        contract = result["intent_contract"]
        active_transfer = [
            item
            for item in contract["actions"]
            if item["predicate"] == "transfer" and item["active_now"]
        ]
        self.assertEqual(len(active_transfer), 1, msg=contract["actions"])
        self.assertTrue(result["risk"]["sensitive"])
        self.assertEqual(
            set(contract["authorization"]["required_grants"]),
            {"external", "sensitive"},
        )
        self.assertEqual(result["tool_gateway"]["decision"], "human_review")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_error_label_with_negated_sensitive_actions_does_not_raise_active_risk(self):
        result = self._compile(
            "只读统计错误标签‘登录会话材料无效’；"
            "不要读取真实会话材料，不要给外部人员，只报告证据",
            scope="sensitive-label-negated-actions",
        )
        contract = result["intent_contract"]
        prohibited = [
            item for item in contract["actions"] if item["polarity"] == "prohibited"
        ]
        self.assertTrue(prohibited)
        self.assertFalse(result["risk"]["sensitive"])
        self.assertEqual(contract["authorization"]["required_grants"], [])
        self.assertNotIn("confirmation_challenge", result["risk"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_confirmation_paraphrases_bind_pending_receipt_without_relaxing_identity(self):
        for utterance in (
            "照此执行",
            "按上述动作办",
            "就这么做",
            "依照刚才的操作执行",
            "按原定动作执行",
        ):
            with self.subTest(utterance=utterance):
                self._assert_continuation_consumes_receipt(utterance)

    def test_approval_prefix_with_veto_keeps_current_utterance_and_receipt_unused(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "approval-prefix-veto"
        vetoes = (
            "可以，但先暂停，不要执行；只读查看当前状态并报告证据",
            "好，不过稍后再说，现在只查看当前状态",
            "确认，但取消原动作，改为只读检查本地状态",
        )
        for utterance in vetoes:
            with self.subTest(utterance=utterance):
                with self._compile_session() as compile_request:
                    first = compile_request(pending_action, scope=scope)
                    receipt = first["risk"]["confirmation_challenge"]["receipt"]
                    vetoed = compile_request(
                        utterance,
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                    accepted_later = compile_request(
                        "照此执行",
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                self.assertEqual(
                    vetoed["intent_contract"]["active_task_source"],
                    "utterance",
                )
                self.assertFalse(
                    vetoed["intent_contract"]["authorization"]["receipt_verified"]
                )
                self.assertFalse(vetoed["completion_contract"]["execute"])
                self.assertFalse(
                    vetoed["risk"].get("receipt_status", {}).get("consumed", False)
                )
                self.assertNotEqual(vetoed["intent_contract"]["operation"], "install")
                self.assertTrue(accepted_later["risk"]["receipt_verified"])
                self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_approval_prefix_with_general_veto_does_not_consume_receipt(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "general-approval-veto"
        vetoes = (
            "同意，但先别运行",
            "可以，不过暂时别做",
            "好，撤销",
        )
        for utterance in vetoes:
            with self.subTest(utterance=utterance):
                with self._compile_session() as compile_request:
                    first = compile_request(pending_action, scope=scope)
                    receipt = first["risk"]["confirmation_challenge"]["receipt"]
                    vetoed = compile_request(
                        utterance,
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                    accepted_later = compile_request(
                        "照此执行",
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                self.assertEqual(
                    vetoed["intent_contract"]["active_task_source"],
                    "utterance",
                )
                self.assertFalse(vetoed["risk"]["receipt_verified"])
                self.assertFalse(
                    vetoed["risk"].get("receipt_status", {}).get("consumed", False)
                )
                self.assertFalse(vetoed["completion_contract"]["execute"])
                self.assertNotEqual(vetoed["intent_contract"]["operation"], "install")
                self.assertTrue(accepted_later["risk"]["receipt_verified"])
                self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_approval_veto_role_matrix_preserves_receipt_for_later_confirmation(self):
        pending_action = self._deeptutor_cli_pending_action()
        cases = (
            "同意，不过先搁置，改成核对当前状态",
            "Okay, hold execution and inspect the current report.",
            "可以，先中止这个动作，只汇报现有证据",
        )
        for index, utterance in enumerate(cases):
            with self.subTest(utterance=utterance):
                scope = f"approval-veto-role-matrix-{index}"
                with self._compile_session() as compile_request:
                    first = compile_request(pending_action, scope=scope)
                    receipt = first["risk"]["confirmation_challenge"]["receipt"]
                    vetoed = compile_request(
                        utterance,
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                    accepted_later = compile_request(
                        "照此执行",
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                self.assertEqual(
                    vetoed["intent_contract"]["active_task_source"], "utterance"
                )
                self.assertFalse(vetoed["risk"]["receipt_verified"])
                self.assertFalse(
                    vetoed["risk"].get("receipt_status", {}).get("consumed", False)
                )
                self.assertFalse(vetoed["completion_contract"]["execute"])
                self.assertNotIn(
                    vetoed["intent_contract"]["operation"], {"install", "change"}
                )
                self.assertTrue(accepted_later["risk"]["receipt_verified"])
                self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_approval_with_action_specific_install_veto_keeps_pending_unconsumed(self):
        pending_action = self._deeptutor_cli_pending_action()
        for index, utterance in enumerate(("可以，但先别装", "好，不过别升级", "确认，先别安装")):
            with self.subTest(utterance=utterance):
                scope = f"action-specific-install-veto-{index}"
                with self._compile_session() as compile_request:
                    first = compile_request(pending_action, scope=scope)
                    receipt = first["risk"]["confirmation_challenge"]["receipt"]
                    vetoed = compile_request(
                        utterance,
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                    accepted_later = compile_request(
                        "照此执行",
                        pending_action=pending_action,
                        confirmation_receipt=receipt,
                        scope=scope,
                    )
                active = [
                    item for item in vetoed["intent_contract"]["actions"] if item["active_now"]
                ]
                self.assertEqual(vetoed["intent_contract"]["active_task_source"], "utterance")
                self.assertFalse(any(item["predicate"] == "install" for item in active))
                self.assertNotIn(
                    "install", vetoed["intent_contract"]["authorization"]["required_grants"]
                )
                self.assertNotIn("confirmation_challenge", vetoed["risk"])
                self.assertFalse(vetoed["risk"]["receipt_verified"])
                self.assertFalse(
                    vetoed["risk"].get("receipt_status", {}).get("consumed", False)
                )
                self.assertFalse(vetoed["completion_contract"]["execute"])
                self.assertTrue(accepted_later["risk"]["receipt_verified"])
                self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_cancel_or_readonly_current_action_does_not_revive_stale_pending_receipt(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "cancel-stale-pending-install"
        with self._compile_session() as compile_request:
            first = compile_request(pending_action, scope=scope)
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            cancelled = compile_request(
                "不要继续，改为只读查看当前状态并报告证据",
                context="旧安装动作正在等待确认。",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
            accepted_later = compile_request(
                "照此执行",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
        self._assert_readonly_status_contract(cancelled)
        self.assertEqual(cancelled["intent_contract"]["active_task_source"], "utterance")
        self.assertFalse(cancelled["intent_contract"]["authorization"]["receipt_verified"])
        self.assertFalse(cancelled["completion_contract"]["execute"])
        self.assertNotEqual(cancelled["intent_contract"]["operation"], "install")
        self.assertNotEqual(
            cancelled["risk"].get("receipt_status", {}).get("reason"),
            "receipt already consumed",
        )
        self.assertTrue(accepted_later["risk"]["receipt_verified"])
        self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_deferral_does_not_verify_or_consume_pending_receipt(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "defer-pending-install"
        with self._compile_session() as compile_request:
            first = compile_request(pending_action, scope=scope)
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            deferred = compile_request(
                "先暂缓，暂时不要执行",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
            accepted_later = compile_request(
                "按上述动作办",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
        self.assertFalse(deferred["intent_contract"]["authorization"]["receipt_verified"])
        self.assertFalse(deferred["completion_contract"]["execute"])
        self.assertFalse(deferred["risk"].get("receipt_status", {}).get("consumed", False))
        self.assertNotEqual(
            deferred["risk"].get("receipt_status", {}).get("reason"),
            "receipt already consumed",
        )
        self.assertTrue(accepted_later["risk"]["receipt_verified"])
        self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_resource_names_do_not_become_actions_without_affirmative_predicates(self):
        for utterance in (
            "只读检查发布清单，不要发布任何内容",
            "核验安装记录，不要安装软件，只报告证据",
            "复查 Skill 清单，不要创建或安装 Skill",
        ):
            with self.subTest(utterance=utterance):
                result = self._compile(utterance, scope="resource-name-readonly-check")
                self._assert_readonly_status_contract(result)

    def test_readonly_acceptance_variants_report_evidence_without_execution(self):
        for utterance in (
            "只读复查当前产物，列出文件和退出码，不要修复，只报告证据",
            "Inspect the current artifacts and list file names plus exit codes; do not fix anything, report evidence only.",
            "核验本地结果并给出证据；禁止修改",
        ):
            with self.subTest(utterance=utterance):
                result = self._compile(utterance, scope="readonly-acceptance-variant")
                self._assert_readonly_status_contract(result)

    def test_stale_pending_does_not_override_explicit_new_readonly_action(self):
        stale_pending = self._deeptutor_cli_pending_action()
        result = self._compile(
            "只读检查新的本地服务健康状态并报告证据，不要安装或修改",
            context="旧安装动作此前等待确认，但现在用户明确切换到新对象。",
            pending_action=stale_pending,
            scope="new-local-health-readonly-action",
        )
        contract = result["intent_contract"]
        self._assert_readonly_status_contract(result)
        self.assertEqual(contract["active_task_source"], "utterance")
        self.assertIn("新的本地服务健康状态", contract["object"]["value"])
        self.assertFalse(contract["authorization"]["receipt_verified"])

    def test_capability_audit_report_keeps_future_installs_inactive(self):
        result = self._compile(
            "请汇报本地能力盘点：现有工具足以继续监控；候选扩展如后续确有缺口才考虑安装，"
            "本轮安装数量为零，安装锁与配置保持原样；现在只核对能力清单并持续观察，"
            "不授权安装或修改配置",
            context="此前有一个无关的本地依赖安装动作等待确认。",
            pending_action=self._deeptutor_cli_pending_action(),
            scope="capability-audit-report-current-wins",
        )

        contract = result["intent_contract"]
        active = [item for item in contract["actions"] if item["active_now"]]
        install_frames = [
            item for item in contract["actions"] if item["predicate"] == "install"
        ]
        self.assertEqual(contract["active_task_source"], "utterance")
        self.assertIn(contract["mode"], {"answer", "diagnose"})
        self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertTrue(
            any(item["predicate"] in {"inspect", "report"} for item in active),
            msg=f"missing current report/inspect frame: {active!r}",
        )
        self.assertFalse(
            any(item["predicate"] == "install" for item in active),
            msg=f"install mention became active: {active!r}",
        )
        self.assertTrue(install_frames)
        self.assertTrue(
            all(
                item["polarity"] == "prohibited"
                or item["temporal_role"] == "conditional"
                for item in install_frames
            ),
            msg=f"install mentions escaped constraint/branch state: {install_frames!r}",
        )
        self.assertNotIn("install", contract["authorization"]["required_grants"])
        self.assertNotIn("confirmation_challenge", result["risk"])
        self.assertFalse(contract["authorization"]["receipt_verified"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_capability_report_install_mentions_use_quantity_time_and_quote_roles(self):
        utterances = (
            "汇总本地能力状态：立即安装数是0；将来若能力不足再考虑安装；当前只检查监控记录",
            "核对能力清单：报告中的‘安装建议’是历史记录，并未执行；现在只读查看现状",
            "请报告现有工具是否够用；候选组件以后才可能安装，本轮不安装也不改配置",
        )
        for utterance in utterances:
            with self.subTest(utterance=utterance):
                result = self._compile(
                    utterance,
                    context="旧的依赖变更仍在等待单独确认。",
                    pending_action=self._deeptutor_cli_pending_action(),
                    scope="capability-report-install-role-matrix",
                )
                contract = result["intent_contract"]
                active = [item for item in contract["actions"] if item["active_now"]]
                self.assertEqual(contract["active_task_source"], "utterance")
                self.assertIn(contract["mode"], {"answer", "diagnose"})
                self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
                self.assertIn(contract["effect"], {"none", "read_local"})
                self.assertFalse(
                    any(item["predicate"] == "install" for item in active),
                    msg=contract["actions"],
                )
                self.assertNotIn("install", contract["authorization"]["required_grants"])
                self.assertNotIn("confirmation_challenge", result["risk"])
                self.assertFalse(contract["authorization"]["receipt_verified"])
                self.assertFalse(result["completion_contract"]["execute"])

    def test_capability_report_bundle_keeps_install_plan_dormant_with_zero_now(self):
        result = self._compile(
            "请确认能力审计结果：推荐组件仅列为后续方案，本轮安装与升级均为零；"
            "安装锁和本地配置没有变化，当前只汇报能力清单并继续监控",
            context="另一个本地安装请求此前等待确认。",
            pending_action=self._deeptutor_cli_pending_action(),
            scope="capability-report-zero-install-bundle",
        )
        contract = result["intent_contract"]
        active = [item for item in contract["actions"] if item["active_now"]]
        self.assertEqual(contract["active_task_source"], "utterance")
        self.assertIn(contract["mode"], {"answer", "diagnose"})
        self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertFalse(any(item["predicate"] == "install" for item in active))
        self.assertNotIn("install", contract["authorization"]["required_grants"])
        self.assertNotIn("confirmation_challenge", result["risk"])
        self.assertFalse(contract["authorization"]["receipt_verified"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_prefaced_cancellation_with_current_report_is_non_business_control(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "prefaced-cancellation-current-report"
        with self._compile_session() as compile_request:
            first = compile_request(pending_action, scope=scope)
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            cancelled = compile_request(
                "请记下：原动作已取消，本轮只报告当前监控状态",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
            accepted_later = compile_request(
                "照此执行",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
        contract = cancelled["intent_contract"]
        self.assertEqual(contract["active_task_source"], "utterance")
        self.assertIn(contract["mode"], {"answer", "diagnose"})
        self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertFalse(cancelled["completion_contract"]["execute"])
        self.assertFalse(cancelled["risk"]["receipt_verified"])
        self.assertFalse(cancelled["risk"].get("receipt_status", {}).get("consumed", False))
        self.assertTrue(accepted_later["risk"]["receipt_verified"])
        self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_prefaced_cancellation_with_short_report_verb_is_non_business_control(self):
        pending_action = self._deeptutor_cli_pending_action()
        scope = "prefaced-cancellation-short-report"
        with self._compile_session() as compile_request:
            first = compile_request(pending_action, scope=scope)
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            cancelled = compile_request(
                "可以先记着，执行动作取消，本轮只报运行情况",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
            accepted_later = compile_request(
                "照此执行",
                pending_action=pending_action,
                confirmation_receipt=receipt,
                scope=scope,
            )
        contract = cancelled["intent_contract"]
        self.assertEqual(contract["active_task_source"], "utterance")
        self.assertIn(contract["mode"], {"answer", "diagnose"})
        self.assertIn(contract["operation"], {"answer", "diagnose", "inspect"})
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertFalse(cancelled["completion_contract"]["execute"])
        self.assertFalse(cancelled["risk"]["receipt_verified"])
        self.assertFalse(cancelled["risk"].get("receipt_status", {}).get("consumed", False))
        self.assertTrue(accepted_later["risk"]["receipt_verified"])
        self.assertTrue(accepted_later["completion_contract"]["execute"])

    def test_conditional_install_and_public_fallback_remain_dormant(self):
        result = self._compile(
            "先只读检查本地依赖状态；如果缺包，确认后再安装；"
            "如果本地证据不足，再考虑上网搜索，现在只报告本地证据",
            scope="conditional-local-diagnosis",
        )
        contract = result["intent_contract"]
        self.assertIn(contract["effect"], {"none", "read_local"})
        self.assertEqual(contract["data_egress"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotEqual(result["routing"]["primary_skill"], "agent-reach")
        self.assertTrue(result["completion_contract"]["verify"])
        self.assertTrue(result["completion_contract"]["report_evidence"])

    def test_t_seg_001_parallel_prohibitions_pair_predicates_and_objects(self):
        case_id = "T-SEG-001"
        result = self._compile(
            "只读核验依赖清单；不要修改配置或安装软件，只报告证据",
            scope="parallel-prohibition-pairing",
        )
        prohibited = [
            item
            for item in result["intent_contract"]["actions"]
            if item["polarity"] == "prohibited"
        ]
        pairs = {(item["predicate"], item["object"]) for item in prohibited}
        self.assertTrue(
            any(predicate == "change" and "修改" in object_value for predicate, object_value in pairs),
            msg=f"{case_id}: missing change/object pairing: {pairs!r}",
        )
        self.assertTrue(
            any(predicate == "install" and "安装" in object_value for predicate, object_value in pairs),
            msg=f"{case_id}: missing install/object pairing: {pairs!r}",
        )
        self.assertTrue(all(not item["active_now"] for item in prohibited), msg=case_id)

    def test_change_synonym_prohibitions_share_one_canonical_predicate(self):
        for verb in ("修改", "更改", "变更"):
            with self.subTest(verb=verb):
                result = self._compile(
                    f"只读检查当前环境；不要{verb}当前环境，不要安装软件，只报告证据",
                    scope="change-synonym-prohibition",
                )
                prohibited = [
                    item
                    for item in result["intent_contract"]["actions"]
                    if item["polarity"] == "prohibited"
                ]
                pairs = {(item["predicate"], item["object"]) for item in prohibited}
                self.assertTrue(
                    any(
                        predicate == "change" and verb in object_value
                        for predicate, object_value in pairs
                    ),
                    msg=f"missing {verb!r} change prohibition: {pairs!r}",
                )
                self.assertTrue(
                    any(
                        predicate == "install" and "安装" in object_value
                        for predicate, object_value in pairs
                    ),
                    msg=f"missing install prohibition: {pairs!r}",
                )

    def test_affirmative_change_synonym_remains_active_change(self):
        result = self._compile(
            "变更当前环境的本地配置",
            scope="affirmative-change-synonym",
        )
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "change")
        self.assertEqual(contract["operation"], "change")
        self.assertEqual(contract["effect"], "write_local")
        self.assertTrue(
            any(
                item["predicate"] == "change"
                and item["polarity"] == "asserted"
                and item["active_now"]
                for item in contract["actions"]
            )
        )

    def test_t_seg_002_active_and_sequential_actions_are_both_preserved(self):
        case_id = "T-SEG-002"
        result = self._compile(
            "先检查本地服务状态，然后启动已经安装的本地服务",
            scope="active-sequential-action-set",
        )
        actions = result["intent_contract"]["actions"]
        action_set = {
            (item["predicate"], item["temporal_role"], item["active_now"])
            for item in actions
        }
        self.assertIn(("inspect", "current", True), action_set, msg=case_id)
        self.assertIn(("start", "sequential", True), action_set, msg=case_id)
        self.assertEqual(result["intent_contract"]["operation"], "start", msg=case_id)
        self.assertTrue(result["completion_contract"]["execute"], msg=case_id)

    def test_t_auth_001_conditional_branch_is_public_and_dormant(self):
        case_id = "T-AUTH-001"
        result = self._compile(
            "先只读检查本地依赖状态；如果缺少组件，确认后再安装；现在只报告本地证据",
            scope="conditional-branch-public-contract",
        )
        branches = result["intent_contract"]["branches"]
        install_branches = [item for item in branches if item["predicate"] == "install"]
        self.assertEqual(len(install_branches), 1, msg=f"{case_id}: {branches!r}")
        branch = install_branches[0]
        self.assertEqual(branch["temporal_role"], "conditional", msg=case_id)
        self.assertEqual(branch["gate_state"], "dormant", msg=case_id)
        self.assertFalse(branch["active_now"], msg=case_id)
        self.assertIn("install", branch["required_grants"], msg=case_id)
        self.assertIsNone(branch["confirmation_challenge"], msg=case_id)
        self.assertFalse(result["completion_contract"]["execute"], msg=case_id)
        self.assertNotIn("install", result["intent_contract"]["authorization"]["required_grants"], msg=case_id)

    def test_t_auth_002_owner_and_digest_bind_active_frame_not_prohibition(self):
        case_id = "T-AUTH-002"
        result = self._compile(
            "在本地 venv 安装解析库；禁止写入 Obsidian vault",
            scope="active-frame-owner-and-digest",
        )
        contract = result["intent_contract"]
        canonical = contract["authorization"]["canonical_action"]
        self.assertEqual(contract["action_owner"]["kind"], "host", msg=case_id)
        self.assertIsNone(result["routing"]["primary_skill"], msg=case_id)
        self.assertIn('"predicate":"install"', canonical, msg=case_id)
        self.assertNotIn('"predicate":"change"', canonical, msg=case_id)
        self.assertNotIn("obsidian", canonical.casefold(), msg=case_id)
        self.assertEqual(
            contract["authorization"]["action_digest"],
            result["risk"]["action_digest"],
            msg=case_id,
        )

    def test_t_ctx_001_explicit_current_action_ignores_stale_pending_frame(self):
        case_id = "T-CTX-001"
        result = self._compile(
            "只读核验新的本地运行记录，只报告证据，不要安装或修改",
            context="旧动作尚未执行。",
            pending_action=self._deeptutor_cli_pending_action(),
            scope="explicit-current-action-over-stale-pending",
        )
        contract = result["intent_contract"]
        self.assertEqual(contract["active_task_source"], "utterance", msg=case_id)
        self.assertIn("新的本地运行记录", contract["object"]["value"], msg=case_id)
        self.assertNotEqual(contract["operation"], "install", msg=case_id)
        self.assertFalse(contract["authorization"]["receipt_verified"], msg=case_id)

    def _assert_receipt_drift_rejected(self, changed_action, *, changed_scope="receipt-tuple-base"):
        original_action = "在本地 venv 安装 parser-lib 到本地工具目录"
        with self._compile_session() as compile_request:
            first = compile_request(original_action, scope="receipt-tuple-base")
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            changed = compile_request(
                "继续",
                pending_action=changed_action,
                confirmation_receipt=receipt,
                scope=changed_scope,
            )
        self.assertFalse(changed["risk"]["receipt_verified"])
        self.assertFalse(changed["completion_contract"]["execute"])
        self.assertIn(
            changed["risk"]["receipt_status"]["reason"],
            {"action mismatch", "scope mismatch", "grant mismatch"},
        )

    def test_t_rec_001_original_canonical_tuple_consumes_receipt_once(self):
        action = "在本地 venv 安装 parser-lib 到本地工具目录"
        with self._compile_session() as compile_request:
            first = compile_request(action, scope="receipt-tuple-success")
            challenge = first["risk"]["confirmation_challenge"]
            confirmed = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=challenge["receipt"],
                scope="receipt-tuple-success",
            )
        self.assertTrue(confirmed["risk"]["receipt_verified"])
        self.assertTrue(confirmed["completion_contract"]["execute"])
        self.assertEqual(
            confirmed["risk"]["action_digest"],
            challenge["action_digest"],
        )

    def test_t_rec_002_predicate_drift_is_rejected(self):
        self._assert_receipt_drift_rejected(
            "从本地 venv 删除 parser-lib 到本地工具目录"
        )

    def test_t_rec_003_object_drift_is_rejected(self):
        self._assert_receipt_drift_rejected(
            "在本地 venv 安装 different-lib 到本地工具目录"
        )

    def test_t_rec_004_destination_drift_is_rejected(self):
        self._assert_receipt_drift_rejected(
            "在本地 venv 安装 parser-lib 并发送到外部工单"
        )

    def test_t_rec_005_scope_drift_is_rejected(self):
        self._assert_receipt_drift_rejected(
            "在本地 venv 安装 parser-lib 到本地工具目录",
            changed_scope="receipt-tuple-other-scope",
        )

    def test_t_rec_006_consumed_receipt_cannot_be_replayed(self):
        action = "在本地 venv 安装 parser-lib 到本地工具目录"
        with self._compile_session() as compile_request:
            first = compile_request(action, scope="receipt-replay")
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            accepted = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=receipt,
                scope="receipt-replay",
            )
            replayed = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=receipt,
                scope="receipt-replay",
            )
        self.assertTrue(accepted["risk"]["receipt_verified"])
        self.assertEqual(replayed["risk"]["receipt_status"]["reason"], "receipt already consumed")
        self.assertFalse(replayed["completion_contract"]["execute"])

    def test_t_rec_007_non_gated_readonly_action_has_no_receipt_digest(self):
        result = self._compile(
            "只读检查本地日志并报告证据，不要修改",
            scope="readonly-no-receipt-digest",
        )
        self.assertNotIn("action_digest", result["risk"])
        self.assertNotIn("confirmation_challenge", result["risk"])
        self.assertEqual(result["intent_contract"]["authorization"]["action_digest"], "")

    def test_t_rec_008_action_mismatch_does_not_consume_receipt(self):
        action = "在本地 venv 安装 parser-lib 到本地工具目录"
        with self._compile_session() as compile_request:
            first = compile_request(action, scope="receipt-mismatch-no-consume")
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            mismatch = compile_request(
                "继续",
                pending_action="在本地 venv 安装 other-lib 到本地工具目录",
                confirmation_receipt=receipt,
                scope="receipt-mismatch-no-consume",
            )
            original = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=receipt,
                scope="receipt-mismatch-no-consume",
            )
        self.assertEqual(mismatch["risk"]["receipt_status"]["reason"], "action mismatch")
        self.assertFalse(mismatch["completion_contract"]["execute"])
        self.assertTrue(original["risk"]["receipt_verified"])
        self.assertTrue(original["completion_contract"]["execute"])

    def test_t_auth_003_bundle_gate_binds_only_active_protected_frames(self):
        result = self._compile(
            "先检查本地依赖，然后安装 parser-lib；如果缺少可选组件，再安装 optional-lib",
            scope="bundle-gate-active-only",
        )
        contract = result["intent_contract"]
        digest = contract["authorization"]["action_digest"]
        active = [item for item in contract["actions"] if item["active_now"]]
        dormant = contract["branches"]
        self.assertTrue(digest)
        self.assertTrue(all(item["bundle_digest"] == digest for item in active))
        self.assertTrue(all(item["bundle_digest"] == "" for item in dormant))
        self.assertTrue(all(item["confirmation_challenge"] is None for item in dormant))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_t_auth_004_sensitive_transfer_frame_keeps_full_grant_set(self):
        result = self._compile(
            "读取本地认证材料，并复制到外部工单",
            scope="sensitive-transfer-frame-grants",
        )
        frames = [
            item
            for item in result["intent_contract"]["actions"]
            if item["predicate"] == "transfer" and item["active_now"]
        ]
        self.assertEqual(len(frames), 1)
        self.assertEqual(set(frames[0]["required_grants"]), {"external", "sensitive"})
        self.assertEqual(frames[0]["gate_state"], "pending_confirmation")
        self.assertTrue(frames[0]["per_frame_digest"])
        self.assertEqual(
            frames[0]["bundle_digest"],
            result["risk"]["confirmation_challenge"]["action_digest"],
        )

    def test_t_auth_005_verified_bundle_allows_protected_frames_only(self):
        action = "在本地 venv 安装 parser-lib 到本地工具目录"
        with self._compile_session() as compile_request:
            first = compile_request(action, scope="verified-bundle-frame-state")
            second = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=first["risk"]["confirmation_challenge"]["receipt"],
                scope="verified-bundle-frame-state",
            )
        frames = [item for item in second["intent_contract"]["actions"] if item["active_now"]]
        self.assertTrue(second["risk"]["receipt_verified"])
        self.assertTrue(all(item["gate_state"] == "allowed" for item in frames if item["required_grants"]))
        self.assertTrue(all(item["bundle_digest"] == second["risk"]["action_digest"] for item in frames))

    def test_t_owner_001_governance_context_does_not_steal_business_owner(self):
        result = self._compile(
            "在本地 venv 安装 parser-lib",
            context="PUA审查只作为治理支持，不拥有当前业务动作。",
            pending_action="",
            scope="business-owner-precedence",
        )
        contract = result["intent_contract"]
        self.assertEqual(contract["action_owner"]["kind"], "host")
        self.assertIsNone(result["routing"]["primary_skill"])
        self.assertEqual(contract["operation"], "install")

    def test_t_rec_009_prepared_receipt_is_not_consumed_when_gate_reviews(self):
        action = "把本地文件发送到外部"
        with self._compile_session() as compile_request:
            first = compile_request(action, scope="prepared-review-no-consume")
            receipt = first["risk"]["confirmation_challenge"]["receipt"]
            reviewed = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=receipt,
                scope="prepared-review-no-consume",
            )
            retried = compile_request(
                "继续",
                pending_action=action,
                confirmation_receipt=receipt,
                scope="prepared-review-no-consume",
            )
        status = reviewed["risk"]["receipt_status"]
        self.assertTrue(status["verified"])
        self.assertTrue(status["prepared"])
        self.assertFalse(status["consumed"])
        self.assertFalse(reviewed["completion_contract"]["execute"])
        self.assertNotEqual(retried["risk"]["receipt_status"]["reason"], "receipt already consumed")


if __name__ == "__main__":
    unittest.main()
