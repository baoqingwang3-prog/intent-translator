import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "agent-reach", "description": "Search GitHub and the public internet"},
        {"name": "skill-lookup", "description": "Search installed and registry Agent Skills"},
        {"name": "skill-creator", "description": "Create and validate Agent Skills"},
        {"name": "prompt-lookup", "description": "Find and improve prompt templates"},
        {"name": "browser", "description": "Run browser and Playwright tests"},
    ],
    "errors": [],
}


class ValueP0Tests(unittest.TestCase):
    def _compiler(self, root: Path) -> IntentCompiler:
        profile = {
            "schema_version": 1,
            "profile_id": "value-p0-user",
            "phrase_mappings": {},
            "memory": {"enabled": False, "adapter": "sqlite", "location": str(root / "memory.db")},
            "study": {
                "enabled": True,
                "goals": ["资格考试", "语言认证"],
                "active_goal": "资格考试",
                "routing": [],
            },
        }
        return IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)

    def _compile(self, utterance: str, *, context: str = "", available_files=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_HOME": str(root),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                    "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
                },
                clear=False,
            ):
                return self._compiler(root).compile(
                    CompileRequest(
                        utterance=utterance,
                        context=context,
                        available_files=available_files or [],
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )

    def test_product_discussion_does_not_route_by_prompt_keyword_or_load_study(self):
        utterance = (
            "朋友说如果你是让GPT生成提示词给codex，codex每次结尾都会回报，"
            "那这个产品还有意义吗"
        )
        result = self._compile(utterance, context="当前在开发产品；更早以前讨论过资格考试")
        self.assertEqual(result["mode"], "answer")
        self.assertIsNone(result["routing"]["primary_skill"])
        self.assertFalse(result["study_context"]["enabled"])
        self.assertEqual(result["current_status"]["goal"], utterance)
        self.assertEqual(result["intent_contract"]["operation"], "answer")
        self.assertEqual(result["intent_contract"]["active_task_source"], "utterance")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_meta_discussion_of_study_policy_does_not_activate_study_or_skill(self):
        result = self._compile(
            "资格考试也不是必行项目，只在指示词明显提到学习考试时复用，开发时不要注入学习目标，也不能擅自调用skill"
        )
        self.assertEqual(result["mode"], "answer")
        self.assertFalse(result["study_context"]["enabled"])
        self.assertIsNone(result["routing"]["primary_skill"])

    def test_explicit_study_request_can_reuse_study_context(self):
        result = self._compile("帮我安排今天的资格考试复习")
        self.assertTrue(result["study_context"]["enabled"])
        self.assertIn("资格考试", result["study_context"]["matched_goals"])

    def test_public_read_search_executes_without_external_write_approval(self):
        result = self._compile("帮我搜索 GitHub 上高星的 Agent Skill")
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["routing"]["primary_skill"], "agent-reach")
        self.assertEqual(result["routing"]["selection_state"], "selected-installed")
        self.assertEqual(result["routing"]["activation_state"], "intended-unverified")
        self.assertTrue(result["routing"]["capability_facts"]["installed"])
        self.assertFalse(result["routing"]["capability_facts"]["activation_verified"])
        self.assertEqual(contract["operation"], "search")
        self.assertEqual(contract["effect"], "read_public")
        self.assertEqual(contract["data_egress"], "public_query")
        self.assertFalse(result["risk"]["external"])
        self.assertFalse(result["clarification_required"])
        self.assertTrue(result["completion_contract"]["execute"])

    def test_playwright_request_is_a_test_action_not_a_discussion(self):
        result = self._compile("或者你可以用 Playwright MCP 去测一下")
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "change")
        self.assertEqual(contract["operation"], "test")
        self.assertEqual(contract["effect"], "read_local")
        self.assertEqual(result["routing"]["primary_skill"], "browser")
        self.assertEqual(result["routing"]["selection_state"], "selected-installed")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_unrelated_request_abstains_instead_of_forcing_a_skill(self):
        result = self._compile("总结一下这个产品目前的优缺点")
        self.assertIsNone(result["routing"]["primary_skill"])
        self.assertTrue(result["routing"]["abstained"])
        self.assertEqual(result["routing"]["selection_state"], "not-selected")

    def test_planned_skill_is_visible_as_unverified_when_discovery_has_no_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            compiler = IntentCompiler(
                registry={"skills": [], "errors": [{"error": "registry unavailable"}]},
                profile={
                    "schema_version": 1,
                    "profile_id": "unverified-route-user",
                    "phrase_mappings": {},
                    "memory": {"adapter": "none"},
                },
                profile_exists=True,
            )
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_HOME": str(root),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                },
                clear=False,
            ):
                result = compiler.compile(
                    CompileRequest(
                        utterance="从零创建一个自定义 Skill",
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )
        self.assertEqual(result["routing"]["primary_skill"], "skill-creator")
        self.assertEqual(result["routing"]["selection_state"], "intended-unverified")
        self.assertFalse(result["routing"]["capability_facts"]["installed"])
        self.assertFalse(result["routing"]["capability_facts"]["activation_verified"])

    def test_private_profile_transfer_remains_action_bound(self):
        result = self._compile("把我的完整用户画像发给外部搜索服务，让它推荐工作")
        contract = result["intent_contract"]
        self.assertEqual(contract["operation"], "transfer")
        self.assertEqual(contract["effect"], "write_external")
        self.assertEqual(contract["data_egress"], "profile")
        self.assertTrue(result["risk"]["external"])
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_vague_external_action_fails_closed_instead_of_inventing_parameters(self):
        result = self._compile("把那个发了吧")
        self.assertIn("object", result["intent_contract"]["required_slots"])
        self.assertIn("destination", result["intent_contract"]["required_slots"])
        self.assertFalse(result["completion_contract"]["execute"])


if __name__ == "__main__":
    unittest.main()
