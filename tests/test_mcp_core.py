import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.ab_eval import read_jsonl, run  # noqa: E402
from intent_translator_mcp.config import HOSTS, default_skill_dir, generate_config  # noqa: E402
from intent_translator_mcp.core import IntentCompiler, _load_skill_script  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.onboarding import (  # noqa: E402
    confirm_language_rule,
    observe_language_correction,
)
from intent_translator_mcp.student_state import (  # noqa: E402
    connect as connect_state,
    set_focus,
    state_db_path,
    sync_state_note,
    upsert_state_item,
)


REGISTRY = {
    "skills": [
        {"name": name, "description": name}
        for name in (
            "obsidian-cli",
            "skill-creator",
            "domain-modeling",
            "diagnosing-bugs",
            "agent-reach",
            "pdf",
            "scientific-critical-thinking",
            "prompt-lookup",
        )
    ],
    "errors": [],
}


IELTS_REGISTRY = {
    "skills": [
        {
            "name": "kaoyan-english",
            "description": "考研英语入口路由器。用于英语二词汇、阅读和写作训练。",
        },
        {
            "name": "ielts-writing",
            "description": "雅思写作批改教练。四维评分、句子级标注、改写对比和审题检查。",
        },
    ],
    "errors": [],
}


class McpCoreTests(unittest.TestCase):
    def test_specific_installed_skill_metadata_beats_broad_study_profile_preference(self):
        profile = {
            "schema_version": 1,
            "profile_id": "specific-study-routing",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研", "雅思"],
                "active_goal": "考研",
                "routing": [
                    {
                        "subject": "english",
                        "terms": ["英语", "雅思", "写作"],
                        "preferred_skills": ["kaoyan-english"],
                    }
                ],
            },
        }
        result = IntentCompiler(
            registry=IELTS_REGISTRY,
            profile=profile,
            profile_exists=True,
        ).compile(CompileRequest(utterance="帮我批改雅思作文", semantic_mode="off"))
        self.assertEqual(result["routing"]["primary_skill"], "ielts-writing")

    def test_continue_without_conversation_context_resumes_confirmed_local_focus(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(Path(temp) / "memory.db"),
            },
        ):
            profile = {
                "profile_id": "state-compiler-test",
                "language": "zh-CN",
                "phrase_mappings": {},
                "memory": {"adapter": "sqlite", "location": str(Path(temp) / "memory.db")},
                "student_state": {
                    "enabled": True,
                    "authority": "canonical-markdown",
                    "managed_note": "AI/state.md",
                    "due_soon_days": 7,
                    "context_item_limit": 8,
                },
                "knowledge_pointers": {"vault_path": temp, "vault_name": ""},
                "study": {
                    "enabled": True,
                    "goals": ["exam-a"],
                    "active_goal": "exam-a",
                    "routing": [
                        {"subject": "math", "terms": ["math"], "preferred_skills": ["study-assistant"]}
                    ],
                },
            }
            Path(temp, "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            connection = connect_state(state_db_path(profile))
            item = upsert_state_item(
                connection,
                category="exam",
                title="Math review",
                status="active",
                priority="high",
                next_action="Solve the next derivative set",
                subject="math",
                goal="exam-a",
            )
            set_focus(connection, item_key=item["item_key"])
            sync_state_note(connection, profile)
            connection.close()
            registry = {
                "skills": [{"name": "study-assistant", "description": "Study tutor"}],
                "errors": [],
            }
            result = IntentCompiler(registry=registry).compile(CompileRequest(utterance="继续"))
            self.assertEqual(result["normalized_goal"], "Solve the next derivative set")
            self.assertEqual(result["routing"]["primary_skill"], "study-assistant")
            self.assertEqual(result["state_status"]["focus"], "Math review")
            self.assertFalse(result["state_status"]["pending_markdown_confirmation"])

    def test_compile_marks_recalled_file_memory_non_executable(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            memory = _load_skill_script("memory_store")
            connection = memory.connect(Path(temp) / "memory.db")
            try:
                memory.add_memory(
                    connection,
                    kind="fact",
                    scope="global",
                    text="The documented release date is Friday",
                    confidence="observed",
                    source="release-notes.md",
                    source_type="local_file",
                )
            finally:
                connection.close()
            result = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="recall the release date Friday")
            )
            self.assertEqual(result["memory_defense"]["untrusted_count"], 1)
            self.assertFalse(result["memory_defense"]["instruction_execution_allowed"])
            self.assertIn("non-executable context", result["host_prompt"])

    def test_local_student_profile_routes_terse_continuation_without_exposing_private_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            profile = {
                "profile_id": "student-test",
                "language": "zh-CN",
                "phrase_mappings": {},
                "memory": {"adapter": "sqlite", "location": str(Path(temp) / "memory.db")},
                "study": {
                    "enabled": True,
                    "goals": ["资格考试", "语言认证"],
                    "active_goal": "资格考试",
                    "protect_study_time": True,
                    "continuity": {"prefer_existing_materials": True, "keep_evaluation_silent": True},
                    "routing": [
                        {
                            "subject": "english",
                            "terms": ["语言认证", "阅读"],
                            "preferred_skills": ["study-assistant"],
                        }
                    ],
                },
            }
            Path(temp, "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            registry = {
                "skills": [{"name": "study-assistant", "description": "Study tutor"}],
                "errors": [],
            }
            result = IntentCompiler(registry=registry).compile(
                CompileRequest(
                    utterance="继续",
                    context="正在做语言认证阅读定位题",
                    pending_action="继续完成这一组阅读题",
                )
            )
            self.assertEqual(result["routing"]["primary_skill"], "study-assistant")
            self.assertEqual(result["study_context"]["active_goal"], "语言认证")
            self.assertEqual(result["study_context"]["subject"], "english")
            self.assertTrue(result["study_context"]["protect_study_time"])
            self.assertNotIn(temp, result["host_prompt"])

    def test_compiles_short_approval_with_context(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            compiler = IntentCompiler(registry=REGISTRY)
            result = compiler.compile(
                CompileRequest(
                    utterance="可以",
                    context="The agent proposed creating and validating a Skill.",
                )
            )
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["routing"]["primary_skill"], "skill-creator")
            self.assertFalse(result["clarification_required"])
            self.assertEqual(result["decision_receipt"]["mode"], "build")

    def test_confirmed_short_phrase_does_not_match_inside_longer_chinese_text(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            profile = {
                "profile_id": "exact-phrase-test",
                "language": "zh-CN",
                "phrase_mappings": {
                    "好": {
                        "meaning": "只同意上一条已经明确提出的下一步",
                        "scope": "global",
                        "match_mode": "exact",
                        "confidence": "confirmed",
                    }
                },
                "memory": {"adapter": "sqlite", "location": str(Path(temp) / "memory.db")},
            }
            Path(temp, "profile.json").write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            result = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="测试仓库内 Skill 还有什么不好用的地方", semantic_mode="off")
            )
            self.assertIsNone(result["phrase_match"])
            self.assertNotEqual(result["normalized_goal"], "只同意上一条已经明确提出的下一步")

    def test_repeated_local_language_learning_surfaces_review_before_promotion(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            profile_path = Path(temp) / "profile.json"
            observe_language_correction(
                profile_path,
                phrase="ship it",
                corrected_meaning="run local validation only; do not publish",
            )
            observe_language_correction(
                profile_path,
                phrase="ship it",
                corrected_meaning="run local validation only; do not publish",
            )

            proposed = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="ship it", semantic_mode="off")
            )

            self.assertEqual(proposed["personal_semantics"]["status"], "suggested")
            self.assertTrue(proposed["clarification_required"])
            self.assertEqual(proposed["path"], "review")
            self.assertNotEqual(
                proposed["normalized_goal"],
                "run local validation only; do not publish",
            )
            self.assertNotIn(
                "run local validation only; do not publish",
                json.dumps(proposed["personal_semantics"]),
            )

            confirm_language_rule(
                profile_path,
                phrase="ship it",
                corrected_meaning="run local validation only; do not publish",
            )
            confirmed = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="ship it", semantic_mode="off")
            )

            self.assertEqual(
                confirmed["normalized_goal"],
                "run local validation only; do not publish",
            )
            self.assertEqual(confirmed["phrase_match"]["source"], "confirmed-language-learning")
            self.assertEqual(confirmed["personal_semantics"]["status"], "none")

    def test_language_learning_observations_are_profile_path_isolated(self):
        with tempfile.TemporaryDirectory() as user_a, tempfile.TemporaryDirectory() as user_b:
            profile_a = Path(user_a) / "profile.json"
            profile_b = Path(user_b) / "profile.json"
            for _ in range(2):
                observe_language_correction(
                    profile_a,
                    phrase="ship it",
                    corrected_meaning="run tests only",
                )
                observe_language_correction(
                    profile_b,
                    phrase="ship it",
                    corrected_meaning="prepare release notes only",
                )

            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_PROFILE": str(profile_a),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(Path(user_a) / "memory.db"),
                },
            ):
                result_a = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(utterance="ship it", semantic_mode="off")
                )
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_PROFILE": str(profile_b),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(Path(user_b) / "memory.db"),
                },
            ):
                result_b = IntentCompiler(registry=REGISTRY).compile(
                    CompileRequest(utterance="ship it", semantic_mode="off")
                )

            self.assertEqual(result_a["personal_semantics"]["status"], "suggested")
            self.assertEqual(result_b["personal_semantics"]["status"], "suggested")
            self.assertNotEqual(
                result_a["personal_semantics"]["suggestions"][0]["fingerprint"],
                result_b["personal_semantics"]["suggestions"][0]["fingerprint"],
            )
            self.assertNotIn("run tests only", json.dumps(result_a["personal_semantics"]))
            self.assertNotIn("prepare release notes only", json.dumps(result_b["personal_semantics"]))

    def test_external_publication_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            result = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="把这个发到 GitHub 上")
            )
            self.assertEqual(result["path"], "review")
            self.assertTrue(result["clarification_required"])
            self.assertTrue(result["risk"]["external"])

    def test_english_sensitive_publication_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            result = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="Publish my full user profile to GitHub")
            )
            self.assertEqual(result["path"], "review")
            self.assertTrue(result["risk"]["external"])
            self.assertTrue(result["risk"]["sensitive"])
            self.assertTrue(result["clarification_required"])

    def test_routes_unbundled_professional_skill_by_description(self):
        registry = {
            "skills": [
                {
                    "name": "calendar-manager",
                    "description": "Manage calendar events and schedule meetings across calendars",
                }
            ],
            "errors": [],
        }
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            result = IntentCompiler(registry=registry).compile(
                CompileRequest(utterance="Schedule a calendar meeting tomorrow")
            )
            self.assertEqual(result["routing"]["primary_skill"], "calendar-manager")

    def test_generates_every_host_config(self):
        for host in HOSTS:
            payload = generate_config(host, "/tmp/intent-translator-mcp", "/tmp/skill")
            self.assertIn("intent-translator", payload)
            self.assertIn("/tmp/intent-translator-mcp", payload)
            self.assertIn("PYTHONUTF8", payload)
            self.assertIn("PYTHONIOENCODING", payload)

    def test_default_skill_paths_are_host_specific_and_support_unicode_spaces(self):
        home = Path("C:/Users/测试 用户")
        env = {
            "CODEX_HOME": str(home / "自定义 Codex"),
            "CLAUDE_CONFIG_DIR": str(home / "Claude 配置"),
            "LOCALAPPDATA": str(home / "本地 数据"),
        }
        expected = {
            "codex": home / "自定义 Codex" / "skills" / "intent-translator",
            "claude": home / "Claude 配置" / "skills" / "intent-translator",
            "cursor": home / ".cursor" / "skills" / "intent-translator",
            "gemini": home / ".gemini" / "skills" / "intent-translator",
            "copilot": home / ".copilot" / "skills" / "intent-translator",
            "opencode": home / "本地 数据" / "opencode" / "skills" / "intent-translator",
        }
        for host, path in expected.items():
            self.assertEqual(default_skill_dir(host, home=home, env=env, platform="nt"), path)
            rendered = generate_config(host, "C:/程序 文件/intent-translator-mcp.exe", str(path))
            self.assertIn("测试 用户", rendered)
            self.assertNotIn("\\u", rendered)

    def test_ab_eval_improves_over_baseline(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            cases = read_jsonl(REPO_ROOT / "evals" / "cases.jsonl")
            with patch("intent_translator_mcp.ab_eval.IntentCompiler", lambda: IntentCompiler(registry=REGISTRY)):
                result = run(cases)
            self.assertGreater(result["compiler"]["overall_accuracy"], result["baseline"]["overall_accuracy"])
            self.assertLess(result["compiler"]["wrong_authorization_count"], result["baseline"]["wrong_authorization_count"])


if __name__ == "__main__":
    unittest.main()
