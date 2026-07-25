import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.studio import (  # noqa: E402
    build_status_payload,
    compile_payload,
    correction_demo_payload,
    create_server,
    studio_asset_dir,
)


class StudioTests(unittest.TestCase):
    def _env(self, root: Path) -> dict[str, str]:
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": "studio-user",
                    "language": "zh-CN",
                    "phrase_mappings": {"private phrase": "private meaning"},
                    "memory": {"adapter": "sqlite", "location": str(root / "memory.db")},
                }
            ),
            encoding="utf-8",
        )
        skill_root = root / "skills"
        for name, description in {
            "agent-reach": "Search and research GitHub and the public internet.",
            "skill-creator": "Create or revise an Agent Skill.",
        }.items():
            skill_dir = skill_root / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {description}\n---\n",
                encoding="utf-8",
            )
        return {
            "INTENT_TRANSLATOR_HOME": str(root),
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_DATA_DIR": str(root / "data"),
            "INTENT_TRANSLATOR_SKILL_ROOTS": str(skill_root),
        }

    def test_status_is_redacted_and_does_not_claim_host_mcp_connection(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, self._env(Path(temp)), clear=False
        ):
            result = build_status_payload()
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertTrue(result["compiler_connected"])
        self.assertEqual(result["host_connection"], "not-verified")
        self.assertIn(result["runtime"]["state"], {"active", "stale", "degraded"})
        self.assertIn("actual_runtime", result["runtime"]["versions"])
        self.assertNotIn(temp, serialized)
        self.assertNotIn("private meaning", serialized)

    def test_compile_returns_only_the_sanitized_studio_view(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, self._env(Path(temp)), clear=False
        ):
            result = compile_payload(
                {
                    "utterance": "好，我们先比较方案，不要发布",
                    "context": "上一条提到以后可能发布到 GitHub",
                    "semantic_mode": "off",
                }
            )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["understanding"], "好，我们先比较方案，不要发布")
        self.assertFalse(result["authorization"]["external"])
        self.assertFalse(result["authorization"]["execute"])
        self.assertEqual(result["authorization"]["action_state"], "answer-only")
        self.assertIn("不要发布", [item["text"] for item in result["authorization"]["constraints"]])
        self.assertIn("runtime", result)
        self.assertNotIn("host_prompt", result)
        self.assertNotIn("student_state", result)
        self.assertNotIn(temp, serialized)
        self.assertNotIn("private meaning", serialized)

    def test_correction_demo_is_synthetic_and_never_changes_the_user_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = self._env(root)
            profile_path = Path(env["INTENT_TRANSLATOR_PROFILE"])
            original = profile_path.read_bytes()
            with patch.dict(os.environ, env, clear=False):
                result = correction_demo_payload()
            self.assertEqual(profile_path.read_bytes(), original)
            self.assertNotEqual(result["before"]["understanding"], result["after"]["understanding"])
            self.assertEqual(result["after"]["understanding"], "创建并验证一个最小 Skill")
            self.assertEqual(result["after"]["selected_skill"], "skill-creator")
            self.assertTrue(result["synthetic_profile"])

    def test_primary_page_uses_plain_language_and_has_expected_controls(self):
        index = (studio_asset_dir() / "index.html").read_text(encoding="utf-8")
        for identifier in (
            'id="intent-input"',
            'id="compile-button"',
            'id="runtime-state"',
            'id="interpretation-options"',
            'id="source-map"',
            'id="undo-interpretation"',
            'id="language-toggle"',
        ):
            self.assertIn(identifier, index)
        for technical_term in ("ExecutionEnvelope", "SQLite", "adapter", "MCP"):
            self.assertNotIn(technical_term, index)
        self.assertTrue((studio_asset_dir() / "styles.css").is_file())
        self.assertTrue((studio_asset_dir() / "app.js").is_file())

    def test_http_server_serves_status_and_real_compile_api(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, self._env(Path(temp)), clear=False
        ):
            server = create_server("127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                    status = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(
                    base + "/api/compile",
                    data=json.dumps(
                        {
                            "utterance": "帮我搜索 GitHub 上高星的 Agent Skill",
                            "semantic_mode": "off",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    compiled = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        self.assertTrue(status["compiler_connected"])
        self.assertEqual(compiled["selected_skill"], "agent-reach")

    def test_server_refuses_network_exposure_without_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_server("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
