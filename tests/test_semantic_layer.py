import json
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
from intent_translator_mcp.semantic import (  # noqa: E402
    ChatCompletionsSemanticAdapter,
    SemanticProposal,
    adapter_from_env,
)


REGISTRY = {
    "skills": [
        {"name": "release-manager", "description": "Publish releases and manage release artifacts"}
    ],
    "errors": [],
}


class FakeAdapter:
    def __init__(self, proposal, *, external=False, name="fake"):
        self.proposal = SemanticProposal.model_validate(proposal)
        self.external = external
        self.name = name
        self.calls = 0

    def interpret(self, payload):
        self.calls += 1
        self.last_payload = payload
        return self.proposal


def compile_with(adapter, utterance, **kwargs):
    temp = tempfile.TemporaryDirectory()
    environment = patch.dict(
        os.environ,
        {
            "INTENT_TRANSLATOR_PROFILE": str(Path(temp.name) / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp.name) / "memory.db"),
        },
    )
    environment.start()
    try:
        return IntentCompiler(registry=REGISTRY, semantic_adapter=adapter).compile(
            CompileRequest(utterance=utterance, **kwargs)
        )
    finally:
        environment.stop()
        temp.cleanup()


class SemanticLayerTests(unittest.TestCase):
    def test_helpful_model_can_explain_metaphor_but_cannot_auto_execute_new_action(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Publish the project publicly",
                "interpretation": "The shelf metaphor means making the project visible to everyone.",
                "mode": "build",
                "confidence": 0.93,
                "primary_skill": "release-manager",
                "risk_hints": ["external", "irreversible"],
            }
        )
        result = compile_with(adapter, "Put this project on the shelf where everyone can see it")
        self.assertEqual(result["semantic"]["status"], "applied")
        self.assertEqual(result["mode"], "build")
        self.assertEqual(result["routing"]["primary_skill"], "release-manager")
        self.assertTrue(result["risk"]["external"])
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_adversarial_model_cannot_lower_deterministic_risk(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Answer the user casually",
                "mode": "answer",
                "confidence": 1.0,
                "risk_hints": [],
                "clarification_recommended": False,
            },
            name="wrong-model",
        )
        result = compile_with(adapter, "Publish my full user profile to GitHub")
        self.assertTrue(result["risk"]["external"])
        self.assertTrue(result["risk"]["sensitive"])
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_unsupported_large_semantic_compression_preserves_original_and_blocks_execution(self):
        utterance = "作为产品经理夸一夸目前的 skill 优点，并反测这些优点可不可以实现"
        adapter = FakeAdapter(
            {
                "normalized_goal": "只同意上一条已经明确提出的下一步",
                "mode": "change",
                "confidence": 0.6,
                "risk_hints": [],
                "clarification_recommended": False,
            },
            name="unsupported-compression",
        )
        result = compile_with(adapter, utterance)
        self.assertEqual(result["normalized_goal"], utterance)
        self.assertEqual(result["semantic_fidelity"]["status"], "rejected-compression")
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertTrue(result["interpretation_gate"]["required"])
        self.assertIn(
            "只同意上一条已经明确提出的下一步",
            [item["text"] for item in result["interpretation_gate"]["candidates"]],
        )

    def test_external_adapter_is_not_called_without_separate_authorization(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Summarize this",
                "mode": "answer",
                "confidence": 0.9,
            },
            external=True,
        )
        result = compile_with(adapter, "Summarize this private note", semantic_mode="required")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(result["semantic"]["status"], "blocked")
        self.assertTrue(result["clarification_required"])

    def test_sensitive_external_adapter_needs_second_authorization(self):
        adapter = FakeAdapter(
            {
                "normalized_goal": "Remember the allergy",
                "mode": "remember",
                "confidence": 0.9,
            },
            external=True,
        )
        result = compile_with(
            adapter,
            "Remember my penicillin allergy",
            semantic_mode="required",
            allow_external_semantic=True,
        )
        self.assertEqual(adapter.calls, 0)
        self.assertIn("sensitive", result["semantic"]["error"])

    def test_adapter_configuration_uses_json_argv_without_shell(self):
        adapter = adapter_from_env(
            {
                "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps(["model-cli", "--json"]),
                "INTENT_TRANSLATOR_SEMANTIC_EXTERNAL": "1",
                "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "7",
            }
        )
        self.assertEqual(adapter.argv, ["model-cli", "--json"])
        self.assertTrue(adapter.external)
        self.assertEqual(adapter.timeout_seconds, 7)

    def test_chat_completions_adapter_supports_local_endpoints(self):
        proposal = {
            "normalized_goal": "Finish the current task",
            "mode": "change",
            "confidence": 0.88,
            "risk_hints": [],
        }
        body = json.dumps(
            {"choices": [{"message": {"content": json.dumps(proposal)}}]}
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return body

        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return Response()

        adapter = ChatCompletionsSemanticAdapter(
            base_url="http://127.0.0.1:11434/v1",
            model="local-model",
            opener=opener,
        )
        result = adapter.interpret({"utterance": "wrap it up", "response_schema": {}})
        self.assertFalse(adapter.external)
        self.assertEqual(result.mode, "change")
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "local-model")

    def test_remote_chat_completions_endpoint_is_external(self):
        adapter = adapter_from_env(
            {
                "INTENT_TRANSLATOR_SEMANTIC_PROVIDER": "chat-completions",
                "INTENT_TRANSLATOR_SEMANTIC_BASE_URL": "https://models.example/v1",
                "INTENT_TRANSLATOR_SEMANTIC_MODEL": "example-model",
            }
        )
        self.assertTrue(adapter.external)


if __name__ == "__main__":
    unittest.main()
