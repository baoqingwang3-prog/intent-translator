import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.studio import (  # noqa: E402
    StudioHandler,
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
        self.assertEqual(result["processing"]["engine"], "deterministic-local")
        self.assertEqual(result["processing"]["model_usage"], "none")
        self.assertFalse(result["processing"]["host_prompt_generated"])
        self.assertEqual(result["sdk_contract"]["operation"], "answer")
        self.assertEqual(result["sdk_contract"]["effect"], "none")
        self.assertIn("input_characters", result["processing"])
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
            'id="example-details"',
            'id="example-summary"',
            'class="context-details" open',
            'id="context-summary"',
            'class="context-fields"',
            'id="compile-button"',
            'id="runtime-state"',
            'id="interpretation-options"',
            'id="source-map"',
            'id="undo-interpretation"',
            'id="language-toggle"',
            'id="processing-engine"',
            'id="model-usage"',
            'id="sdk-output"',
            'id="copy-sdk-output"',
        ):
            self.assertIn(identifier, index)
        for technical_term in ("ExecutionEnvelope", "SQLite", "adapter", "MCP"):
            self.assertNotIn(technical_term, index)
        self.assertTrue((studio_asset_dir() / "styles.css").is_file())
        app = (studio_asset_dir() / "app.js").read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("focus", loadStatus)', app)
        self.assertIn("window.setInterval(loadStatus, 5000)", app)

    def test_asset_rejects_unsafe_names_before_accessing_the_asset_root(self):
        handler = object.__new__(StudioHandler)
        handler.send_error = Mock()
        absolute_asset = str((Path.cwd() / "index.html").resolve())

        with patch("intent_translator_mcp.studio.studio_asset_dir") as asset_dir:
            for name in (
                "",
                "../index.html",
                "assets/../index.html",
                r"assets\..\index.html",
                "assets//index.html",
                absolute_asset,
                "index.exe",
            ):
                with self.subTest(name=name):
                    handler.send_error.reset_mock()
                    StudioHandler._asset(handler, name)
                    handler.send_error.assert_called_once_with(HTTPStatus.NOT_FOUND)
            asset_dir.assert_not_called()

    def test_asset_allows_nested_files_with_expected_static_extensions(self):
        handler = object.__new__(StudioHandler)
        handler.send_error = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "css" / "app.css"
            asset.parent.mkdir()
            asset.write_bytes(b"body {}")
            with patch("intent_translator_mcp.studio.studio_asset_dir", return_value=root):
                StudioHandler._asset(handler, "css/app.css")

        handler.send_error.assert_not_called()
        handler.send_response.assert_called_once_with(HTTPStatus.OK)
        handler.send_header.assert_any_call("Content-Type", "text/css; charset=utf-8")
        self.assertEqual(handler.wfile.getvalue(), b"body {}")

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
