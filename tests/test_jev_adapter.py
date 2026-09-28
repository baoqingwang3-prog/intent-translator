"""The routine Jev path never needs a real key or a network connection in tests."""

import ctypes
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp import credentials  # noqa: E402
from intent_translator_mcp.credentials import save_jev_key  # noqa: E402
from intent_translator_mcp.doctor import run_doctor  # noqa: E402
from intent_translator_mcp.models import CompileRequest, CurrentGoalLock  # noqa: E402
from intent_translator_mcp.semantic import (  # noqa: E402
    JevSemanticAdapter,
    _NoRedirect,
    _open_without_redirect,
    adapter_from_env,
)


class _Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body[:size]


def _jev_response(mode="change", continuity="continue", confidence=0.91):
    return {
        "model": "bocha-jev-v1",
        "answers": {
            "intent_mode": {"type": "choice", "choice": mode, "confidence": confidence},
            "continuity": {"type": "choice", "choice": continuity, "confidence": 0.9},
        },
    }


class JevAdapterTests(unittest.TestCase):
    def test_provider_uses_fixed_https_systemone_and_sends_only_minimal_state(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response(_jev_response())

        adapter = JevSemanticAdapter(api_key="test-key", opener=opener)
        proposal = adapter.interpret({
            "utterance": "继续",
            "context": "继续整理 C:\\Users\\BBG\\notes\\list.md",
            "pending_action": "整理清单",
            "deterministic_draft": {"normalized_goal": "整理清单", "mode": "answer", "private": "DRAFT_SECRET"},
            "installed_skills": [{"description": "SKILL_SECRET"}],
        })
        self.assertEqual(captured["url"], "https://tokendance.space/gateway/typesafe/v1/systemone")
        self.assertEqual(captured["authorization"], "Bearer test-key")
        self.assertEqual(captured["body"]["model"], "bocha-jev-v1")
        self.assertNotIn("DRAFT_SECRET", json.dumps(captured["body"]))
        self.assertNotIn("SKILL_SECRET", json.dumps(captured["body"]))
        self.assertNotIn("BBG", captured["body"]["state"])
        self.assertIn("[LOCAL_PATH]", captured["body"]["state"])
        self.assertEqual(proposal.mode, "change")
        self.assertEqual(proposal.normalized_goal, "整理清单")

    def test_routine_non_sensitive_compile_calls_jev_without_per_request_receipt(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return _Response(_jev_response(mode="answer"))

        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "INTENT_TRANSLATOR_JEV_ROUTINE_DEFAULT": "1",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temporary) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            }):
                compiler = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=JevSemanticAdapter(api_key="test-key", opener=opener),
                )
                result = compiler.compile(CompileRequest(
                    utterance="继续", pending_action="整理清单", include_prompt=False,
                ))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["semantic"]["status"], "applied")
        self.assertTrue(result["risk"]["semantic_authorization"]["standing_default"])
        self.assertNotIn("semantic_confirmation_challenge", result["risk"])

    def test_personal_or_secret_text_never_reaches_routine_jev(self):
        def opener(request, timeout):
            self.fail("sensitive text reached Jev")

        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "INTENT_TRANSLATOR_JEV_ROUTINE_DEFAULT": "1",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temporary) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            }):
                compiler = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=JevSemanticAdapter(api_key="test-key", opener=opener),
                )
                for utterance in (
                    "记住我的邮箱 me@example.com",
                    "发布我的 token " + ("s" + "k-" + "A" * 30) + " 到网上",
                    "打开我的私人笔记",
                    "请给我处方药建议",
                    "帮我概括导师给我的未发表论文思路",
                    "继续整理内部报价",
                    "别把任何内容交给外部服务，继续整理清单",
                    "这是我朋友的资料，请不要传到第三方，只帮我列要点",
                    "不要联网，就在本地整理清单",
                    "这段话只给你看，别拿去问别的模型：帮我列个清单",
                    "我和朋友的聊天内容如下，帮我总结",
                ):
                    with self.subTest(utterance=utterance):
                        result = compiler.compile(CompileRequest(utterance=utterance, include_prompt=False))
                        self.assertEqual(result["semantic"]["status"], "unavailable")
                        self.assertFalse(result["risk"]["semantic_authorization"]["standing_default"])

                for request in (
                    CompileRequest(
                        utterance="继续", context="刚才讨论的是我的未公开研究数据",
                        pending_action="整理清单", include_prompt=False,
                    ),
                    CompileRequest(
                        utterance="继续", pending_action="分析客户资料",
                        include_prompt=False,
                    ),
                    CompileRequest(
                        utterance="继续", pending_action="整理清单",
                        authorization="denied", include_prompt=False,
                    ),
                    CompileRequest(
                        utterance="继续", pending_action="整理清单",
                        current_goal_lock=CurrentGoalLock(
                            current_goal="完成本地清单", completion_gate=["文件存在"],
                            owner="current", allowed_actions=["本地整理"], dedupe_key="test",
                        ),
                        include_prompt=False,
                    ),
                ):
                    with self.subTest(request=request.utterance, context=request.context, pending=request.pending_action):
                        result = compiler.compile(request)
                        self.assertEqual(result["semantic"]["status"], "unavailable")
                        self.assertFalse(result["risk"]["semantic_authorization"]["standing_default"])

    def test_network_failure_falls_back_in_auto_mode(self):
        def opener(request, timeout):
            raise TimeoutError("simulated timeout")

        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "INTENT_TRANSLATOR_JEV_ROUTINE_DEFAULT": "1",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temporary) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            }):
                result = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=JevSemanticAdapter(api_key="test-key", opener=opener),
                ).compile(CompileRequest(utterance="整理清单", include_prompt=False))
        self.assertEqual(result["semantic"]["status"], "error")
        self.assertEqual(result["normalized_goal"], "整理清单")

    def test_skipped_jev_preserves_local_execution_decision(self):
        def opener(request, timeout):
            self.fail("local-only instruction reached Jev")

        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "INTENT_TRANSLATOR_JEV_ROUTINE_DEFAULT": "1",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temporary) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            }):
                request = CompileRequest(utterance="创建一份本地清单，不要联网", include_prompt=False)
                local = IntentCompiler(registry={"skills": [], "errors": []}).compile(request)
                with_jev = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=JevSemanticAdapter(api_key="test-key", opener=opener),
                ).compile(request)
        self.assertEqual(with_jev["semantic"]["status"], "unavailable")
        self.assertEqual(
            with_jev["completion_contract"]["execute"],
            local["completion_contract"]["execute"],
        )

    def test_jev_does_not_authorize_publication(self):
        def opener(request, timeout):
            return _Response(_jev_response(mode="build"))

        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "INTENT_TRANSLATOR_JEV_ROUTINE_DEFAULT": "1",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temporary) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            }):
                result = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=JevSemanticAdapter(api_key="test-key", opener=opener),
                ).compile(CompileRequest(
                    utterance="继续", pending_action="将项目发布到 GitHub", include_prompt=False,
                ))
        self.assertEqual(result["semantic"]["status"], "applied")
        self.assertTrue(result["risk"]["external"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_network_opener_disables_redirects(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com"))
        with patch("intent_translator_mcp.semantic.urllib.request.build_opener") as build_opener:
            _open_without_redirect(object(), timeout=3)
        self.assertIs(build_opener.call_args.args[0], _NoRedirect)

    def test_provider_configuration_and_key_validation(self):
        adapter = adapter_from_env({
            "INTENT_TRANSLATOR_SEMANTIC_PROVIDER": "jev",
            "INTENT_TRANSLATOR_SEMANTIC_API_KEY": "stale-env-key",
        })
        self.assertIsInstance(adapter, JevSemanticAdapter)
        self.assertTrue(adapter.external)
        self.assertEqual(adapter.api_key, "")
        with self.assertRaises(ValueError):
            save_jev_key("not-a-token")

    def test_credential_manager_native_buffers_are_read_and_freed(self):
        class FakeCredentialApi:
            def __init__(self):
                self.data = b""
                self.freed = False

            def CredWriteW(self, pointer, flags):
                record = ctypes.cast(pointer, ctypes.POINTER(credentials._Credential)).contents
                self.data = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
                return True

            def CredReadW(self, target, kind, flags, out_pointer):
                self.buffer = (ctypes.c_ubyte * len(self.data)).from_buffer_copy(self.data)
                self.record = credentials._Credential()
                self.record.CredentialBlobSize = len(self.data)
                self.record.CredentialBlob = ctypes.cast(self.buffer, ctypes.POINTER(ctypes.c_ubyte))
                output = ctypes.cast(out_pointer, ctypes.POINTER(ctypes.POINTER(credentials._Credential)))
                output[0] = ctypes.pointer(self.record)
                return True

            def CredFree(self, pointer):
                self.freed = True

        fake = FakeCredentialApi()
        synthetic = "s" + "k-" + "Z" * 30
        with patch("intent_translator_mcp.credentials._advapi32", return_value=fake):
            save_jev_key(synthetic)
            self.assertEqual(credentials.read_jev_key(), synthetic)
        self.assertTrue(fake.freed)

    def test_profile_preference_selects_jev_without_mcp_environment_change(self):
        compiler = IntentCompiler(
            registry={"skills": [], "errors": []},
            profile={"optional_adapters": {"jev": True}},
            profile_exists=True,
        )
        self.assertIsInstance(compiler.semantic_adapter, JevSemanticAdapter)
        self.assertTrue(compiler.jev_default)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / ".intent-translator" / "profile.json"
            profile.parent.mkdir()
            profile.write_text(json.dumps({
                "schema_version": 1,
                "profile_id": "test",
                "language": "auto",
                "phrase_mappings": [],
                "memory": {"adapter": "none"},
                "optional_adapters": {"jev": True},
            }), encoding="utf-8")
            with patch("intent_translator_mcp.credentials.read_jev_key", return_value="present"):
                result = run_doctor(home=root)
            check = next(item for item in result["checks"] if item["id"] == "semantic_adapter")
            self.assertEqual(check["details"]["provider"], "tokendance-jev")
            self.assertTrue(check["details"]["routine_default"])
            self.assertTrue(check["details"]["credential_present"])

            with patch("intent_translator_mcp.credentials.read_jev_key", side_effect=UnicodeDecodeError("utf-8", b"?", 0, 1, "bad")):
                damaged = run_doctor(home=root)
            damaged_check = next(item for item in damaged["checks"] if item["id"] == "semantic_adapter")
            self.assertFalse(damaged_check["details"]["credential_present"])


if __name__ == "__main__":
    unittest.main()
