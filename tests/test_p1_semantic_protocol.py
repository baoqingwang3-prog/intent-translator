import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler, _load_skill_script  # noqa: E402
from intent_translator_mcp.models import CompileRequest, InterpretationOption  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "obsidian-cli", "description": "Read and update selected Obsidian notes"},
        {"name": "agent-reach", "description": "Search GitHub and the public internet"},
    ],
    "errors": [],
}


class P1SemanticProtocolTests(unittest.TestCase):
    def _profile(self, root: Path) -> dict:
        return {
            "schema_version": 1,
            "profile_id": "synthetic-p1-user",
            "phrase_mappings": {},
            "memory": {"enabled": True, "adapter": "sqlite", "location": str(root / "memory.db")},
            "study": {"enabled": True, "goals": ["private-study-goal"], "active_goal": "private-study-goal"},
        }

    def _compile(self, root: Path, utterance: str, **kwargs):
        with patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_HOME": str(root),
                "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
            },
            clear=False,
        ):
            compiler = IntentCompiler(registry=REGISTRY, profile=self._profile(root), profile_exists=True)
            return compiler.compile(
                CompileRequest(
                    utterance=utterance,
                    semantic_mode="off",
                    include_prompt=False,
                    **kwargs,
                )
            )

    def test_project_correction_applies_locally_but_unknown_scope_abstains(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            connection = memory.connect(root / "memory.db")
            try:
                memory.add_correction(
                    connection,
                    scope="project-nine",
                    trigger_text="Obsidian也接一下",
                    trigger_context="Obsidian也接一下",
                    wrong_interpretation="直接修改 Obsidian 文件",
                    correct_interpretation="先给接入方案，暂不改文件",
                    correction="先给接入方案，暂不改文件",
                    source="user-confirmed-natural-language-correction",
                    edit={"field": "operation", "replacement": "answer"},
                    retain_days=30,
                )
            finally:
                connection.close()

            local = self._compile(root, "Obsidian也接一下", scope="project-nine")
            isolated = self._compile(root, "Obsidian也接一下", scope="project-ten")

        self.assertEqual(local["intent_contract"]["operation"], "answer")
        self.assertEqual(local["intent_contract"]["effect"], "none")
        self.assertFalse(local["completion_contract"]["execute"])
        self.assertTrue(any(item.get("kind") == "correction-case" for item in local["prompt_source_map"]))

        self.assertEqual(isolated["corrections"], [])
        self.assertTrue(isolated["interpretation_gate"]["required"])
        self.assertFalse(isolated["completion_contract"]["execute"])
        labels = [item["text"] for item in isolated["interpretation_gate"]["candidates"]]
        self.assertEqual(
            labels,
            ["先给接入方案，暂不改文件", "直接接入并修改文件", "都不是"],
        )
        self.assertFalse(isolated["study_context"]["enabled"])
        self.assertNotEqual(isolated["current_status"]["goal"], "private-study-goal")

    def test_number_text_and_option_id_resolve_the_same_previous_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = self._compile(root, "Obsidian也接一下", scope="project-ten")["interpretation_gate"]
            options = [InterpretationOption.model_validate(item) for item in gate["candidates"]]
            results = [
                self._compile(
                    root,
                    wording,
                    scope="project-ten",
                    interpretation_gate_id=gate["id"],
                    interpretation_options=options,
                )
                for wording in ("1", "第一个", "interpretation-1")
            ]

        for result in results:
            self.assertEqual(result["gate_resolution"]["option_id"], "interpretation-1")
            self.assertEqual(result["intent_contract"]["operation"], "answer")
            self.assertEqual(result["intent_contract"]["effect"], "none")
            self.assertFalse(result["completion_contract"]["execute"])
            self.assertFalse(result["study_context"]["enabled"])

    def test_isolated_number_without_gate_context_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._compile(Path(temp), "1", scope="project-ten")

        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertIn("interpretation_context", result["intent_contract"]["required_slots"])

    def test_recipient_adaptation_changes_preview_not_authorization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            personal = self._compile(root, "把现在这个发给我女朋友看看，别公开")
            investor = self._compile(root, "先做一份给 VC 看的本地预览，不要发送")
            engineer = self._compile(root, "生成给工程师看的本地项目介绍，先不要外发")

        contract = personal["intent_contract"]["communication"]
        self.assertEqual(contract["relationship_context"], "personal")
        self.assertEqual(contract["recipient_expertise"], "unknown")
        self.assertEqual(contract["recommended_artifact"], "local-preview")
        self.assertEqual(contract["template"], "general-overview")
        self.assertTrue(contract["needs_purpose_question"])
        self.assertIn("source-code", contract["excluded_disclosures"])
        self.assertIn("profile", contract["excluded_disclosures"])
        self.assertFalse(personal["completion_contract"]["execute"])
        self.assertEqual(personal["tool_gateway"]["decision"], "human_review")

        self.assertEqual(investor["intent_contract"]["communication"]["template"], "investor-overview")
        self.assertEqual(
            investor["intent_contract"]["communication"]["sections"],
            ["problem", "target-users", "differentiation", "evidence", "risks", "ask"],
        )
        self.assertEqual(engineer["intent_contract"]["communication"]["template"], "engineering-overview")
        self.assertEqual(
            engineer["intent_contract"]["communication"]["sections"],
            ["architecture", "tests", "contribution-entry"],
        )
        self.assertFalse(investor["risk"]["external"])
        self.assertFalse(engineer["risk"]["external"])


if __name__ == "__main__":
    unittest.main()
