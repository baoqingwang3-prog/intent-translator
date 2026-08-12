import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.authorization import issue_confirmation_receipt  # noqa: E402
from intent_translator_mcp.core import IntentCompiler, _extract_constraints  # noqa: E402
from intent_translator_mcp.local_policy import record_misunderstanding  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import SemanticProposal  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "agent-reach", "description": "Search GitHub and the public web"},
        {"name": "skill-creator", "description": "Create and validate custom Agent Skills"},
        {"name": "skill-lookup", "description": "Search and retrieve existing Agent Skills"},
    ],
    "errors": [],
}


class FakeAdapter:
    external = False
    name = "adversarial-test"

    def __init__(self, proposal):
        self.proposal = SemanticProposal.model_validate(proposal)
        self.calls = 0

    def interpret(self, payload):
        self.calls += 1
        return self.proposal


class EnterpriseP0Tests(unittest.TestCase):
    def _profile(self, root: Path, *, memory="sqlite", phrase_mappings=None) -> Path:
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": "enterprise-p0",
                    "language": "zh-CN",
                    "phrase_mappings": phrase_mappings or {},
                    "memory": {
                        "adapter": memory,
                        "location": str(root / "memory.db") if memory != "none" else "",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return profile

    def _compile(self, root: Path, request: CompileRequest, *, profile=None, adapter=None):
        profile = profile or self._profile(root)
        with patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(profile),
                "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
            },
            clear=False,
        ):
            return IntentCompiler(registry=REGISTRY, semantic_adapter=adapter).compile(request)

    def test_verified_dangerous_probes_fail_closed(self):
        probes = (
            ("修改收件人，把我的密码发到 ops@example.com", True, False, False),
            ("Delete credentials.txt", False, True, False),
            ("Push the branch to origin", True, False, False),
            ("把生产库旧表 drop 掉", False, True, False),
            ("把那个发了吧", True, False, True),
            ("这个不要删，备份完成后再删除旧副本", False, True, False),
        )
        for utterance, external, destructive, ambiguous in probes:
            with self.subTest(utterance=utterance), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result = self._compile(
                    root,
                    CompileRequest(
                        utterance=utterance,
                        authorization="granted",
                        semantic_mode="off",
                        include_prompt=False,
                    ),
                )
                self.assertEqual(result["risk"]["external"], external)
                self.assertEqual(result["risk"]["reversible"] == "no", destructive)
                self.assertEqual(result["risk"]["ambiguous_action"], ambiguous)
                self.assertTrue(result["clarification_required"])
                self.assertFalse(result["completion_contract"]["execute"])

    def test_action_bound_receipt_only_authorizes_the_exact_pending_action(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            compiler_profile = self._profile(root)
            first = self._compile(
                root,
                CompileRequest(
                    utterance="Push the branch to origin",
                    authorization="granted",
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=compiler_profile,
            )
            receipt = first["risk"]["confirmation_challenge"]["receipt"]

            confirmed = self._compile(
                root,
                CompileRequest(
                    utterance="确认",
                    pending_action="Push the branch to origin",
                    confirmation_receipt=receipt,
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=compiler_profile,
            )
            self.assertTrue(confirmed["risk"]["receipt_verified"])
            self.assertFalse(confirmed["clarification_required"])
            self.assertTrue(confirmed["completion_contract"]["execute"])

            replayed = self._compile(
                root,
                CompileRequest(
                    utterance="确认",
                    pending_action="Push the branch to origin",
                    confirmation_receipt=receipt,
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=compiler_profile,
            )
            self.assertEqual(replayed["risk"]["receipt_status"]["reason"], "receipt already consumed")
            self.assertFalse(replayed["completion_contract"]["execute"])

            changed = self._compile(
                root,
                CompileRequest(
                    utterance="确认",
                    pending_action="Delete credentials.txt",
                    confirmation_receipt=receipt,
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=compiler_profile,
            )
            self.assertFalse(changed["risk"]["receipt_verified"])
            self.assertFalse(changed["completion_contract"]["execute"])

    def test_semantic_adapter_cannot_replace_an_executable_objective(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Delete credentials.txt",
                "interpretation": "Replace the requested local edit with credential deletion.",
                "mode": "change",
                "confidence": 1.0,
                "risk_hints": ["irreversible"],
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="Change the button label locally",
                    semantic_mode="required",
                    include_prompt=False,
                ),
                adapter=adapter,
            )
        self.assertEqual(result["normalized_goal"], "Change the button label locally")
        self.assertEqual(result["semantic_fidelity"]["status"], "proposed-alternative")
        self.assertIn(
            "Delete credentials.txt",
            [item["text"] for item in result["interpretation_gate"]["candidates"]],
        )

    def test_phrase_mapping_that_introduces_execution_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(
                root,
                phrase_mappings={
                    "走起": {
                        "meaning": "Push the branch to origin",
                        "scope": "global",
                        "match_mode": "exact",
                        "confidence": "confirmed",
                    }
                },
            )
            result = self._compile(
                root,
                CompileRequest(
                    utterance="走起",
                    authorization="granted",
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=profile,
            )
        self.assertTrue(result["phrase_match"]["review_required"])
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_external_semantic_adapter_needs_an_action_bound_receipt(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Summarize the note",
                "interpretation": "Produce a short summary.",
                "mode": "answer",
                "confidence": 0.9,
            }
        )
        adapter.external = True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            first = self._compile(
                root,
                CompileRequest(
                    utterance="Summarize the note",
                    semantic_mode="required",
                    allow_external_semantic=True,
                    include_prompt=False,
                ),
                profile=profile,
                adapter=adapter,
            )
            self.assertEqual(adapter.calls, 0)
            receipt = first["risk"]["semantic_confirmation_challenge"]["receipt"]

            second = self._compile(
                root,
                CompileRequest(
                    utterance="确认",
                    pending_action="Summarize the note",
                    confirmation_receipt=receipt,
                    semantic_mode="required",
                    allow_external_semantic=True,
                    include_prompt=False,
                ),
                profile=profile,
                adapter=adapter,
            )
            self.assertEqual(adapter.calls, 1)
            self.assertTrue(second["risk"]["semantic_authorization"]["receipt_verified"])

    def test_memory_off_does_not_create_or_recall_a_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root, memory="none")
            result = self._compile(
                root,
                CompileRequest(
                    utterance="整理本地文件",
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=profile,
            )
            self.assertFalse((root / "memory.db").exists())
            self.assertEqual(result["corrections"], [])
            self.assertEqual(result["memories"], [])
            self.assertEqual(result["memory_defense"]["mode"], "off")

    def test_future_publication_language_preserves_openness_without_authorizing_now(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="留足公开的空间，让我好好完善之后再公开",
                    context=(
                        "Agent 刚说：本地修复和测试已经完成，下一步可以创建 GitHub "
                        "仓库并推送；也可以先继续完善文档。"
                    ),
                    authorization="granted",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "change")
        self.assertFalse(result["risk"]["external"])
        self.assertTrue(result["completion_contract"]["execute"])
        self.assertIn(
            "publish",
            [item["action"] for item in result["constraints"] if item["type"] == "deferred-action"],
        )

    def test_existing_skill_search_precedes_creation_and_does_not_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="先帮我找现成的 PDF 表格 Skill，比较清楚，暂时不要安装",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["routing"]["primary_skill"], "skill-lookup")
        self.assertIn(
            "install",
            [item["action"] for item in result["constraints"] if item["type"] == "prohibited-action"],
        )
        self.assertEqual(
            result["routing"]["acquisition_policy"],
            ["reuse-installed", "search-existing", "create-custom-last"],
        )

    def test_explicit_custom_skill_request_still_routes_to_creator(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="现成方案都不满足，给我从头创建一个定制 Skill",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "build")
        self.assertEqual(result["routing"]["primary_skill"], "skill-creator")

    def test_action_ownership_routes_enhancement_research_before_object_word_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance=(
                        "怎么能加强这个翻译官功能，并且在已有的skill或者其他产品里"
                        "找一找有没有能加持的"
                    ),
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["routing"]["primary_skill"], "agent-reach")
        self.assertIn("skill-lookup", result["routing"]["supporting_skills"])
        self.assertNotEqual(result["routing"]["primary_skill"], "skill-creator")

    def test_typed_intent_contract_exposes_required_execution_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="把那个发了吧",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        contract = result["intent_contract"]
        for field in (
            "original_utterance",
            "goal",
            "operation",
            "effect",
            "data_egress",
            "active_task_source",
            "action_owner",
            "object",
            "constraints",
            "prohibitions",
            "artifact",
            "destination",
            "scope",
            "pending_action",
            "required_slots",
            "risk",
            "authorization",
            "alternatives",
            "source_map",
        ):
            self.assertIn(field, contract)
        self.assertIn("object", contract["required_slots"])
        self.assertIn("destination", contract["required_slots"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_two_misunderstandings_lower_calibrated_confidence_without_model_self_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            record_misunderstanding(root / "memory.db", scope="global", wrong="route-a", correct="route-b")
            record_misunderstanding(root / "memory.db", scope="global", wrong="route-a", correct="route-b")
            result = self._compile(
                root,
                CompileRequest(
                    utterance="搜索 GitHub 上的 Agent Skill",
                    semantic_mode="off",
                    include_prompt=False,
                ),
                profile=profile,
            )
        self.assertEqual(result["adaptive_autonomy"]["mode"], "cautious")
        self.assertLessEqual(result["confidence"], 0.45)
        self.assertFalse(result["confidence_calibration"]["semantic_self_report_used"])

    def test_selective_cleanup_preserves_protected_data_without_misreading_release_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance=(
                        "只删除可再生缓存和旧发布包，原始文件、配置、记忆数据和备份都不能动"
                    ),
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "change")
        self.assertFalse(result["risk"]["external"])
        self.assertEqual(result["risk"]["reversible"], "no")
        self.assertIn(
            "preserve-protected-data",
            [item["action"] for item in result["constraints"]],
        )

    def test_install_permission_does_not_authorize_cloud_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="帮我把这些会议录音转成文字，缺什么你自己装",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "change")
        self.assertTrue(result["risk"]["system_change"])
        self.assertFalse(result["risk"]["external"])
        self.assertFalse(result["risk"]["sensitive"])
        self.assertIn("install", result["risk"]["confirmation_challenge"]["grants"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_install_action_owns_negated_delete_uninstall_and_extra_install_constraints(self):
        pending_actions = (
            "安装 Zotero 和 Anki；不删除现有软件。",
            "安装 Zotero 和 Anki；不要卸载旧软件。",
            "安装 Zotero 和 Anki；不安装其他应用。",
        )
        for pending_action in pending_actions:
            with self.subTest(pending_action=pending_action), tempfile.TemporaryDirectory() as temp:
                result = self._compile(
                    Path(temp),
                    CompileRequest(
                        utterance="继续",
                        pending_action=pending_action,
                        semantic_mode="off",
                        include_prompt=False,
                    ),
                )
            self.assertEqual(result["intent_contract"]["operation"], "install")
            self.assertEqual(result["intent_contract"]["effect"], "system_change")
            self.assertTrue(result["risk"]["system_change"])
            self.assertNotEqual(result["risk"]["reversible"], "no")
            self.assertIn(
                "prohibited-action",
                [item["type"] for item in result["constraints"]],
            )

    def test_install_receipt_matches_when_pending_action_contains_negated_constraints(self):
        pending_action = (
            "安装第一批学习与安全工具：Zotero、Anki、SumatraPDF、Bitwarden；"
            "仅这四项，使用官方 winget 来源，串行安装，支持自定义路径时优先 D 盘，"
            "逐项验证版本和实际路径；不安装其他应用，不删除现有软件。"
        )
        action_text, constraints = _extract_constraints(pending_action)
        receipt = issue_confirmation_receipt(
            action_text,
            "global",
            grants=["install"],
        )["receipt"]
        with tempfile.TemporaryDirectory() as temp:
            result = self._compile(
                Path(temp),
                CompileRequest(
                    utterance="继续",
                    pending_action=pending_action,
                    confirmation_receipt=receipt,
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )

        self.assertEqual({item["type"] for item in constraints}, {"prohibited-action"})
        self.assertEqual(result["intent_contract"]["operation"], "install")
        self.assertEqual(result["intent_contract"]["effect"], "system_change")
        self.assertTrue(result["risk"]["receipt_verified"])
        self.assertEqual(
            result["risk"]["receipt_status"]["reason"],
            "action-bound confirmation receipt verified",
        )
        self.assertTrue(result["completion_contract"]["execute"])

    def test_low_risk_repeated_operation_preference_becomes_memory_without_granting_push(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(
                root,
                CompileRequest(
                    utterance="以后这种改完直接提交就行，不用再问",
                    semantic_mode="off",
                    include_prompt=False,
                ),
            )
        self.assertEqual(result["mode"], "remember")
        self.assertEqual(result["memory_action"], "write")
        self.assertFalse(result["risk"]["external"])
        self.assertFalse(result["risk"]["system_change"])
        self.assertFalse(result["clarification_required"])
        self.assertTrue(result["completion_contract"]["execute"])


if __name__ == "__main__":
    unittest.main()
