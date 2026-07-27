import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp import IntentCompiler, IntentTranslatorSDK  # noqa: E402


class SDKTests(unittest.TestCase):
    def _sdk(self, root: Path) -> IntentTranslatorSDK:
        profile = {
            "schema_version": 1,
            "profile_id": "sdk-test",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
        }
        registry = {
            "skills": [
                {
                    "name": "agent-reach",
                    "description": "Search and research GitHub and the public internet.",
                },
                {
                    "name": "obsidian-cli",
                    "description": "Read and change an Obsidian vault.",
                },
            ],
            "errors": [],
        }
        compiler = IntentCompiler(
            registry=registry,
            profile=profile,
            profile_exists=True,
            entrypoint="sdk-test",
        )
        return IntentTranslatorSDK(compiler)

    def test_compile_returns_typed_contract_without_host_prompt_or_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._sdk(Path(temp)).compile(
                "帮我搜索 GitHub 上高星的 Agent Skill",
                semantic_mode="off",
            )
        self.assertEqual(result.contract.operation, "search")
        self.assertEqual(result.contract.effect, "read_public")
        self.assertEqual(result.selected_skill, "agent-reach")
        self.assertEqual(result.tool_decision, "allow")
        self.assertTrue(result.can_execute)
        self.assertFalse(result.model_used)
        self.assertNotIn("host_prompt", result.to_dict())
        self.assertNotIn("memories", result.to_dict())
        self.assertNotIn("corrections", result.to_dict())
        self.assertEqual(result.value_receipt["benefit_claim"], "observable-activity-only")
        self.assertEqual(result.value_receipt["counterfactual_status"], "not-run")
        self.assertTrue(result.value_receipt["skill_route_selected"])

    def test_compile_exposes_internal_diagnostics_only_when_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._sdk(Path(temp)).compile(
                "search GitHub for Agent Skills",
                semantic_mode="off",
                include_diagnostics=True,
            )
        self.assertIn("memories", result.to_dict())
        self.assertIn("corrections", result.to_dict())

    def test_resolve_binds_number_to_previous_interpretation_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            sdk = self._sdk(Path(temp))
            first = sdk.compile("Obsidian也接一下", scope="project-a", semantic_mode="off")
            self.assertTrue(first.requires_clarification)
            self.assertIsNotNone(first.interpretation_gate)
            resolved = sdk.resolve(first, "1", semantic_mode="off")
        self.assertEqual(resolved.contract.operation, "answer")
        self.assertEqual(resolved.contract.effect, "none")
        self.assertFalse(resolved.can_execute)
        self.assertEqual(
            resolved.to_dict()["gate_resolution"]["option_id"],
            "interpretation-1",
        )

    def test_receipt_only_exposes_compiler_issued_action_bound_challenge(self):
        with tempfile.TemporaryDirectory() as temp:
            sdk = self._sdk(Path(temp))
            action = "把 dist/release.whl 发布到 GitHub Release"
            first = sdk.compile(action, semantic_mode="off")
            challenge = sdk.receipt(first)
            self.assertIsNotNone(challenge)
            approved = sdk.compile(
                "确认",
                pending_action=action,
                semantic_mode="off",
                confirmation_receipt=challenge["receipt"],
            )
        self.assertTrue(approved.can_execute)
        self.assertTrue(approved.to_dict()["risk"]["receipt_verified"])

    def test_check_is_readonly_when_memory_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._sdk(root).check(
                "publish the release",
                impact="high",
                reversible="no",
                external=True,
            )
            serialized = json.dumps(result)
        self.assertTrue(result["confirmation_required"])
        self.assertFalse(result["blocked"])
        self.assertNotIn(str(root), serialized)


if __name__ == "__main__":
    unittest.main()
