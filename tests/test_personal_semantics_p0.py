import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler, _load_skill_script  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.tool_gateway import decide_tool_access  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "agent-reach", "description": "Search GitHub and the public internet"},
        {"name": "browser", "description": "Run browser and Playwright tests"},
        {"name": "skill-creator", "description": "Create and validate Agent Skills"},
    ],
    "errors": [],
}


class PersonalSemanticsP0Tests(unittest.TestCase):
    def _profile(self, root: Path, *, memory: bool = True) -> dict:
        return {
            "schema_version": 1,
            "profile_id": "synthetic-p0-user",
            "phrase_mappings": {},
            "memory": {
                "enabled": memory,
                "adapter": "sqlite" if memory else "none",
                "location": str(root / "memory.db"),
            },
            "study": {
                "enabled": True,
                "goals": ["考研", "雅思"],
                "active_goal": "考研",
                "routing": [],
            },
        }

    def _compile(self, root: Path, utterance: str, **kwargs):
        profile = kwargs.pop("profile", self._profile(root))
        with patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_HOME": str(root),
                "INTENT_TRANSLATOR_PROFILE": str(root / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
            },
            clear=False,
        ):
            return IntentCompiler(
                registry=REGISTRY,
                profile=profile,
                profile_exists=True,
            ).compile(
                CompileRequest(
                    utterance=utterance,
                    semantic_mode="off",
                    include_prompt=False,
                    **kwargs,
                )
            )

    def test_non_study_work_never_uses_a_stored_study_goal_as_current_goal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._compile(root, "升级 personal-intent-compiler 的个人语义学习能力")

        self.assertFalse(result["study_context"]["enabled"])
        self.assertEqual(
            result["current_status"]["goal"],
            "升级 personal-intent-compiler 的个人语义学习能力",
        )
        self.assertNotIn("考研", result["current_status"]["goal"])
        self.assertNotIn("雅思", result["current_status"]["goal"])
        self.assertFalse(result["adaptive_autonomy"]["automatic_restore_allowed"])
        self.assertTrue(result["adaptive_autonomy"]["restore_requires_confirmation"])

    def test_confirmed_correction_case_keeps_structured_local_edit_and_provenance(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            connection = memory.connect(Path(temp) / "memory.db")
            try:
                saved = memory.add_correction(
                    connection,
                    scope="project-alpha",
                    trigger_text="搜索 GitHub 上高星 Skill",
                    trigger_context="搜索 GitHub 上高星 Skill",
                    wrong_interpretation="创建一个 Skill",
                    correct_interpretation="搜索公开 GitHub 项目",
                    correction="搜索公开 GitHub 项目",
                    source="user-confirmed-natural-language-correction",
                    edit={"field": "operation", "replacement": "search"},
                    retain_days=30,
                )
                found = memory.search_corrections(
                    connection,
                    query="帮我找 GitHub 上高星的 Skill",
                    scope="project-alpha",
                    track_access=False,
                )
            finally:
                connection.close()

        self.assertEqual(found[0]["id"], saved["id"])
        self.assertEqual(found[0]["wrong_interpretation"], "创建一个 Skill")
        self.assertEqual(found[0]["correct_interpretation"], "搜索公开 GitHub 项目")
        self.assertEqual(found[0]["source"], "user-confirmed-natural-language-correction")
        self.assertEqual(found[0]["edit"], {"field": "operation", "replacement": "search"})
        self.assertTrue(found[0]["expires_at"])
        self.assertTrue(found[0]["local_only"])

    def test_similar_confirmed_correction_is_retrieved_and_explained_without_rewriting_the_goal(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            connection = memory.connect(root / "memory.db")
            try:
                memory.add_correction(
                    connection,
                    scope="global",
                    trigger_text="搜索 GitHub 上高星 Skill",
                    trigger_context="搜索 GitHub 上高星 Skill",
                    wrong_interpretation="创建 Skill",
                    correct_interpretation="搜索 GitHub 上的公开项目",
                    correction="搜索 GitHub 上的公开项目",
                    source="user-confirmed-natural-language-correction",
                    edit={"field": "operation", "replacement": "search"},
                    retain_days=30,
                )
            finally:
                connection.close()

            result = self._compile(root, "帮我搜索 GitHub 上高星的 Agent Skill")

        self.assertTrue(result["corrections"])
        self.assertEqual(result["corrections"][0]["source"], "user-confirmed-natural-language-correction")
        self.assertFalse(result["interpretation_gate"]["required"])
        self.assertEqual(result["normalized_goal"], "帮我搜索 GitHub 上高星的 Agent Skill")
        self.assertEqual(result["intent_contract"]["operation"], "search")
        self.assertEqual(result["routing"]["primary_skill"], "agent-reach")
        self.assertTrue(
            any(item.get("kind") == "correction-case" for item in result["prompt_source_map"])
        )
        self.assertTrue(result["completion_contract"]["execute"])

    def test_ambiguous_external_action_produces_typed_choices_and_human_review(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._compile(Path(temp), "把那个发了吧")

        gate = result["interpretation_gate"]
        self.assertTrue(gate["required"])
        self.assertGreaterEqual(len(gate["candidates"]), 2)
        self.assertLessEqual(len(gate["candidates"]), 3)
        self.assertTrue(all("intent" in item for item in gate["candidates"]))
        self.assertEqual(result["tool_gateway"]["decision"], "human_review")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_clear_local_test_is_allowed_without_interpretation_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._compile(Path(temp), "或者你可以用 Playwright MCP 测一下")

        self.assertFalse(result["interpretation_gate"]["required"])
        self.assertEqual(result["intent_contract"]["operation"], "test")
        self.assertEqual(result["routing"]["primary_skill"], "browser")
        self.assertEqual(result["tool_gateway"]["decision"], "allow")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_deterministic_gateway_cannot_be_lowered_by_a_model_hint(self):
        decision = decide_tool_access(
            operation="publish",
            effect="write_external",
            data_egress="private_file",
            risk={
                "blocked": False,
                "confirmation_required": True,
                "external": True,
                "sensitive": True,
                "reversible": "unknown",
            },
            clarification_required=False,
            semantic_suggestion="allow",
        )
        self.assertEqual(decision["decision"], "human_review")
        self.assertFalse(decision["semantic_suggestion_applied"])

    def test_execution_verification_can_write_back_only_a_confirmed_local_correction(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            connection = memory.connect(Path(temp) / "memory.db")
            try:
                unconfirmed = memory.verify_execution_outcome(
                    connection,
                    scope="project-alpha",
                    utterance="用 Playwright 测一下",
                    expected_goal="回答测试方法",
                    expected_operation="answer",
                    expected_skill="",
                    actual_goal="运行 Playwright 测试",
                    actual_operation="test",
                    actual_skill="browser",
                    success=False,
                    user_confirmed_correction=False,
                )
                self.assertIsNone(unconfirmed["written_correction"])
                self.assertEqual(
                    memory.search_corrections(connection, query="Playwright", track_access=False),
                    [],
                )

                confirmed = memory.verify_execution_outcome(
                    connection,
                    scope="project-alpha",
                    utterance="用 Playwright 测一下",
                    expected_goal="回答测试方法",
                    expected_operation="answer",
                    expected_skill="",
                    actual_goal="运行 Playwright 测试",
                    actual_operation="test",
                    actual_skill="browser",
                    success=False,
                    user_confirmed_correction=True,
                    retain_days=30,
                )
                exported = memory.export_store(connection)
            finally:
                connection.close()

        self.assertFalse(confirmed["matched"])
        self.assertEqual(confirmed["written_correction"]["correct_interpretation"], "运行 Playwright 测试")
        self.assertEqual(confirmed["written_correction"]["edit"], {"field": "operation", "replacement": "test"})
        self.assertEqual(len(exported["tables"]["execution_outcomes"]), 2)
        self.assertEqual(
            exported["tables"]["execution_outcomes"][-1]["correction_id"],
            confirmed["written_correction"]["id"],
        )

    def test_natural_language_correction_generates_a_local_edit_only_after_confirmation(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            connection = memory.connect(Path(temp) / "memory.db")
            try:
                pending = memory.suggest_correction(
                    connection,
                    message="不是回答测试方法，我是说直接用 Playwright 测",
                    scope="project-alpha",
                    previous_behavior="回答测试方法",
                    replacement="运行 Playwright 测试",
                    trigger_context="用 Playwright 测一下",
                    wrong_interpretation="回答测试方法",
                    correct_interpretation="运行 Playwright 测试",
                    edit_field="operation",
                    edit_replacement="test",
                    retain_days=30,
                )
                self.assertEqual(
                    memory.search_corrections(connection, query="Playwright", track_access=False),
                    [],
                )
                confirmed = memory.confirm_pending_correction(connection, pending["id"])
            finally:
                connection.close()

        self.assertEqual(
            confirmed["correction"]["edit"],
            {"field": "operation", "replacement": "test"},
        )
        self.assertEqual(
            confirmed["correction"]["correct_interpretation"],
            "运行 Playwright 测试",
        )

    def test_blocked_action_is_denied_by_the_tool_gateway(self):
        decision = decide_tool_access(
            operation="answer",
            effect="none",
            data_egress="none",
            risk={"blocked": True, "confirmation_required": False},
            clarification_required=False,
        )
        self.assertEqual(decision["decision"], "deny")

    def test_missing_profile_returns_generic_behavior_without_personal_claims(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_HOME": str(root),
                    "INTENT_TRANSLATOR_PROFILE": str(root / "missing-profile.json"),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(root / "missing-memory.db"),
                },
                clear=False,
            ):
                result = IntentCompiler(
                    registry=REGISTRY,
                    profile={"schema_version": 1, "profile_id": "generic", "phrase_mappings": {}, "memory": {"adapter": "none"}},
                    profile_exists=False,
                ).compile(
                    CompileRequest(
                        utterance="继续",
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )

        self.assertEqual(result["personalization_status"]["mode"], "generic")
        self.assertFalse(result["personalization_status"]["claims_personal_knowledge"])
        self.assertNotIn("考研", result["normalized_goal"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_schema_four_migrates_to_five_without_losing_correction_data(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "memory.db"
            legacy = sqlite3.connect(db)
            legacy.execute(
                """
                CREATE TABLE corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    trigger_text TEXT NOT NULL,
                    correction TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    retrieved_count INTEGER NOT NULL DEFAULT 0,
                    heeded_count INTEGER NOT NULL DEFAULT 0,
                    recurred_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, trigger_text, correction)
                )
                """
            )
            legacy.execute(
                """
                INSERT INTO corrections(
                    scope, trigger_text, correction, severity, created_at, updated_at
                ) VALUES ('global', '继续测试', '恢复具体测试任务', 'high', '2026-01-01', '2026-01-01')
                """
            )
            legacy.execute("PRAGMA user_version = 4")
            legacy.commit()
            legacy.close()

            connection = memory.connect(db)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                stored = connection.execute("SELECT * FROM corrections").fetchone()
                self.assertEqual(stored["correction"], "恢复具体测试任务")
                self.assertIn("edit_json", stored.keys())
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_outcomes'"
                    ).fetchone()
                )
            finally:
                connection.close()
            self.assertEqual(len(list(root.glob("memory.db.bak-v4-*"))), 1)

    def test_exact_alpha_acceptance_inputs_preserve_task_and_authorization_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = self._compile(
                root,
                "可以",
                pending_action="编译提示词交给当前 Agent，不上传或发布",
            )
            self.assertFalse(prompt["risk"]["external"])
            self.assertNotEqual(prompt["tool_gateway"]["decision"], "deny")

            resumed = self._compile(
                root,
                "恢复了",
                pending_action="继续完善本地测试，不上传 GitHub",
            )
            self.assertEqual(resumed["normalized_goal"], "继续完善本地测试，不上传 GitHub")
            self.assertEqual(resumed["current_status"]["authorization"], "unknown")
            self.assertFalse(resumed["risk"]["external"])

            protected = self._compile(
                root,
                "恢复了",
                pending_action="发布仓库到 GitHub",
            )
            self.assertEqual(protected["current_status"]["authorization"], "unknown")
            self.assertEqual(protected["tool_gateway"]["decision"], "human_review")
            self.assertFalse(protected["completion_contract"]["execute"])


if __name__ == "__main__":
    unittest.main()
