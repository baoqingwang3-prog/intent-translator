import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp import __version__  # noqa: E402
from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


REGISTRY = {
    "skills": [
        {
            "name": "agent-reach",
            "description": "Search and research GitHub and the public internet",
        },
        {
            "name": "skill-creator",
            "description": "Create and validate reusable Agent Skills",
        },
        {
            "name": "obsidian-cli",
            "description": "Read and update explicitly selected Obsidian notes",
        },
    ],
    "errors": [],
}


class AlphaP0RegressionTests(unittest.TestCase):
    def _profile(self, root: Path, phrase_mappings=None) -> Path:
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": "alpha-regression-user",
                    "language": "zh-CN",
                    "phrase_mappings": phrase_mappings or {},
                    "memory": {"adapter": "sqlite", "location": str(root / "memory.db")},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return profile

    def _env(self, root: Path, profile: Path) -> dict[str, str]:
        return {
            "INTENT_TRANSLATOR_HOME": str(root),
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_DATA_DIR": str(root / "data"),
            "INTENT_TRANSLATOR_SKILL_DIR": str(root / "skill"),
        }

    def _install_version_markers(self, root: Path, version: str) -> None:
        skill = root / "skill"
        skill.mkdir(parents=True)
        (skill / "VERSION").write_text(version + "\n", encoding="utf-8")
        command = root / "data" / "mcp" / "runtimes" / version / "intent-translator-mcp.exe"
        command.parent.mkdir(parents=True)
        command.touch()
        current = root / "data" / "mcp" / "current.json"
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_text(
            json.dumps({"version": version, "command": str(command)}),
            encoding="utf-8",
        )

    def test_compile_exposes_active_runtime_handshake_and_receipt_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            self._install_version_markers(root, __version__)
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY, entrypoint="mcp").compile(
                    CompileRequest(utterance="整理本地测试")
                )

            status = result["runtime_status"]
            self.assertEqual(status["state"], "active")
            self.assertEqual(status["entrypoint"], "mcp")
            self.assertEqual(status["versions"]["actual_runtime"], __version__)
            self.assertEqual(status["versions"]["active_skill"], __version__)
            self.assertEqual(status["versions"]["profile_schema"], 1)
            self.assertFalse(status["stale_runtime"])
            self.assertEqual(result["decision_receipt"]["runtime_version"], __version__)
            self.assertEqual(result["decision_receipt"]["runtime_state"], "active")

    def test_compile_marks_old_loaded_process_stale_against_new_disk_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            self._install_version_markers(root, "9.9.9")
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY, entrypoint="mcp").compile(
                    CompileRequest(utterance="检查当前版本")
                )

            status = result["runtime_status"]
            self.assertEqual(status["state"], "stale")
            self.assertTrue(status["stale_runtime"])
            self.assertTrue(status["restart_required"])
            self.assertIn("running process", " ".join(status["reasons"]))

    def test_short_confirmation_contains_mappings_never_hijack_long_requests(self):
        cases = {
            "可以": "或者你可以用playWright mcp去测一下",
            "好": "好，我们先比较方案，不要发布",
            "继续": "继续完善本地测试，不上传 GitHub",
            "ok": "OK, run only the local tests and do not publish",
        }
        for phrase, utterance in cases.items():
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = self._profile(
                    root,
                    {
                        phrase: {
                            "meaning": "只同意上一条已经明确提出的下一步",
                            "scope": "global",
                            "match_mode": "contains",
                            "confidence": "confirmed",
                        }
                    },
                )
                with patch.dict(os.environ, self._env(root, profile), clear=False):
                    result = IntentCompiler(registry=REGISTRY).compile(
                        CompileRequest(utterance=utterance, semantic_mode="off")
                    )
                self.assertIsNone(result["phrase_match"])
                self.assertEqual(result["normalized_goal"], utterance)

    def test_negative_publication_scope_is_a_constraint_not_an_external_action(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(
                        utterance="好，我们先比较方案，不要发布",
                        context="上一条提到以后可能发布到 GitHub",
                        semantic_mode="off",
                    )
                )
            self.assertEqual(result["mode"], "answer")
            self.assertFalse(result["risk"]["external"])
            self.assertFalse(result["completion_contract"]["execute"])
            self.assertIn("不要发布", [item["text"] for item in result["constraints"]])

    def test_search_action_owns_routing_even_when_the_object_is_a_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(
                        utterance="帮我搜索 GitHub 上高星的 Agent Skill",
                        semantic_mode="off",
                    )
                )
            self.assertEqual(result["mode"], "search")
            self.assertEqual(result["routing"]["primary_skill"], "agent-reach")

    def test_continue_prefers_specific_pending_action_and_maps_its_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(
                root,
                {
                    "继续": {
                        "meaning": "继续当前流程",
                        "scope": "global",
                        "match_mode": "exact",
                        "confidence": "confirmed",
                    }
                },
            )
            pending = "继续完善本地测试，不上传 GitHub"
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(
                        utterance="继续",
                        pending_action=pending,
                        authorization="granted",
                        semantic_mode="off",
                    )
                )
            self.assertEqual(result["normalized_goal"], pending)
            self.assertFalse(result["risk"]["external"])
            self.assertIn("不上传 GitHub", [item["text"] for item in result["constraints"]])
            self.assertTrue(
                any(item["kind"] == "context-resumption" for item in result["prompt_source_map"])
            )

    def test_explicit_local_work_with_no_upload_remains_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = self._profile(root)
            utterance = "继续完善本地测试，不上传 GitHub"
            with patch.dict(os.environ, self._env(root, profile), clear=False):
                result = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(
                        utterance=utterance,
                        authorization="granted",
                        semantic_mode="off",
                    )
                )
            self.assertEqual(result["normalized_goal"], utterance)
            self.assertEqual(result["mode"], "change")
            self.assertFalse(result["risk"]["external"])
            self.assertTrue(result["completion_contract"]["execute"])

    def test_coordinated_negative_publish_clause_stays_a_constraint(self):
        cases = (
            (
                "Update the five-user trial docs and run local tests; "
                "do not create a remote, push, or publish.",
                "publish",
            ),
            (
                "更新五用户陌生用户彩排文档，运行本地测试；"
                "不得创建 remote、push 或公开发布",
                "公开发布",
            ),
        )
        for pending, prohibited_text in cases:
            with self.subTest(pending=pending), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = self._profile(root)
                with patch.dict(os.environ, self._env(root, profile), clear=False):
                    result = IntentCompiler(registry=REGISTRY).compile(
                        CompileRequest(
                            utterance="Continue",
                            pending_action=pending,
                            authorization="granted",
                            semantic_mode="off",
                        )
                    )
                self.assertEqual(result["normalized_goal"], pending)
                self.assertFalse(result["risk"]["external"])
                self.assertTrue(result["completion_contract"]["execute"])
                self.assertTrue(
                    any(
                        item["type"] == "prohibited-action"
                        and prohibited_text in item["text"]
                        for item in result["constraints"]
                    )
                )

    def test_negative_reminder_does_not_hide_a_publish_action(self):
        cases = (
            "Do not forget to publish the release.",
            "不要忘记发布这个版本。",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = self._profile(root)
                with patch.dict(os.environ, self._env(root, profile), clear=False):
                    result = IntentCompiler(registry=REGISTRY).compile(
                        CompileRequest(utterance=utterance, semantic_mode="off")
                    )
                self.assertTrue(result["risk"]["external"])
                self.assertTrue(result["clarification_required"])
                self.assertFalse(result["completion_contract"]["execute"])

    def test_short_confirmation_without_a_specific_previous_action_never_executes(self):
        for utterance in ("可以", "好", "继续", "OK"):
            with self.subTest(utterance=utterance), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = self._profile(root)
                with patch.dict(os.environ, self._env(root, profile), clear=False):
                    result = IntentCompiler(registry=REGISTRY).compile(
                        CompileRequest(utterance=utterance, semantic_mode="off")
                    )
                self.assertTrue(result["clarification_required"])
                self.assertFalse(result["completion_contract"]["execute"])
                self.assertEqual(
                    result["short_confirmation_status"]["state"],
                    "missing-specific-action",
                )

    def test_versioned_alpha_adversarial_cases(self):
        cases = [
            json.loads(line)
            for line in (REPO_ROOT / "evals" / "adversarial-alpha.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(cases), 7)
        for case in cases:
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = self._profile(root, case.get("phrase_mappings"))
                with patch.dict(os.environ, self._env(root, profile), clear=False):
                    result = IntentCompiler(registry=REGISTRY).compile(
                        CompileRequest(
                            utterance=case["utterance"],
                            context=case.get("context", ""),
                            pending_action=case.get("pending_action", ""),
                            authorization=case.get("authorization", "unknown"),
                            semantic_mode="off",
                        )
                    )
                expected = case["expected"]
                if "normalized_goal" in expected:
                    self.assertEqual(result["normalized_goal"], expected["normalized_goal"])
                if "mode" in expected:
                    self.assertEqual(result["mode"], expected["mode"])
                if "primary_skill" in expected:
                    self.assertEqual(result["routing"]["primary_skill"], expected["primary_skill"])
                if "external" in expected:
                    self.assertEqual(result["risk"]["external"], expected["external"])
                if "execute" in expected:
                    self.assertEqual(result["completion_contract"]["execute"], expected["execute"])
                if "clarification" in expected:
                    self.assertEqual(result["clarification_required"], expected["clarification"])
                if "phrase_match" in expected:
                    self.assertEqual(result["phrase_match"] is not None, expected["phrase_match"])
                if "constraint" in expected:
                    self.assertIn(expected["constraint"], [item["text"] for item in result["constraints"]])
                if "short_confirmation_state" in expected:
                    self.assertEqual(
                        result["short_confirmation_status"]["state"],
                        expected["short_confirmation_state"],
                    )


if __name__ == "__main__":
    unittest.main()
