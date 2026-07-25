import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.models import (  # noqa: E402
    CheckRequest,
    CompileRequest,
    MemoryDefenseRequest,
)
from intent_translator_mcp.server import (  # noqa: E402
    compiler,
    intent_check,
    intent_compile,
    intent_memory_defense,
)
from intent_translator_mcp.core import _load_skill_script  # noqa: E402


class ServerContractTests(unittest.TestCase):
    def _env(self, root: Path) -> dict[str, str]:
        return {
            "INTENT_TRANSLATOR_PROFILE": str(root / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
        }

    def test_readonly_tools_do_not_create_a_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="Review the local architecture",
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )
                checked = intent_check(CheckRequest(goal="Review the local architecture"))
                defense = intent_memory_defense(MemoryDefenseRequest())

            self.assertFalse((root / "memory.db").exists())
            self.assertEqual(compiled["mode"], "answer")
            self.assertEqual(checked["watch_for"], [])
            self.assertEqual(defense["memory_mode"], "empty")

    def test_compact_default_omits_private_and_diagnostic_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profile_id": "compact-contract",
                        "phrase_mappings": {},
                        "memory": {"adapter": "none", "location": ""},
                        "study": {
                            "enabled": True,
                            "goals": ["private-exam-goal"],
                            "active_goal": "private-exam-goal",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, self._env(root), clear=False):
                compact = intent_compile(
                    CompileRequest(
                        utterance="Review the local architecture",
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )
                diagnostics = intent_compile(
                    CompileRequest(
                        utterance="Review the local architecture",
                        semantic_mode="off",
                        include_prompt=False,
                        include_diagnostics=True,
                    )
                )

            serialized = json.dumps(compact, ensure_ascii=False)
            self.assertLessEqual(len(serialized), 3500)
            self.assertNotIn("private-exam-goal", serialized)
            self.assertNotIn("student_state", compact)
            self.assertNotIn("corrections", compact)
            self.assertIn("student_state", diagnostics)

    def test_compiler_cache_reuses_instances_and_meets_latency_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                first = compiler()
                second = compiler()
                self.assertIs(first, second)

                request = CompileRequest(
                    utterance="Review the local architecture",
                    semantic_mode="off",
                    include_prompt=False,
                )
                intent_compile(request)
                timings = []
                for _ in range(20):
                    start = time.perf_counter()
                    intent_compile(request)
                    timings.append((time.perf_counter() - start) * 1000)

            timings.sort()
            self.assertLessEqual(timings[18], 75.0)

    def test_packaged_hash_manifest_rejects_tampered_runtime_skill_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "intent-translator"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            source = REPO_ROOT / "skills" / "intent-translator" / "scripts"
            for name in ("memory_store.py", "semantic_search.py"):
                shutil.copy2(source / name, scripts / name)
            (scripts / "memory_store.py").write_text(
                (scripts / "memory_store.py").read_text(encoding="utf-8") + "\n# tampered\n",
                encoding="utf-8",
            )
            _load_skill_script.cache_clear()
            try:
                with patch.dict(
                    os.environ,
                    {"INTENT_TRANSLATOR_SKILL_DIR": str(skill)},
                    clear=False,
                ):
                    with self.assertRaisesRegex(RuntimeError, "integrity mismatch"):
                        _load_skill_script("memory_store")
            finally:
                _load_skill_script.cache_clear()


if __name__ == "__main__":
    unittest.main()
