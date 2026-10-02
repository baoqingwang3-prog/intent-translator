"""Preserve actor receipts across semantic vetoes in the integrated compiler."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(
    os.environ.get("INTENT_TRANSLATOR_TEST_REPO", Path(__file__).resolve().parents[1])
)
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.authorization import reset_receipt_state  # noqa: E402
from intent_translator_mcp.core import IntentCompiler, _risk  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import SemanticProposal  # noqa: E402
from intent_translator_mcp import server  # noqa: E402


ACTION = "在本地 venv 安装 parser-lib 并记录目录"
ACTOR = "alice@corp"


class VetoAdapter:
    name = "integration-semantic-veto"
    external = False

    def __init__(self, status):
        self.proposal = SemanticProposal(
            normalized_goal=ACTION,
            interpretation="Preserve the exact pending action; apply the explicit control veto.",
            mode="change",
            confidence=0.99,
            control_status=status,
            clarification_recommended=status == "clarify",
        )

    def interpret(self, payload):
        return self.proposal


class Pr16SemanticReceiptIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="intent-semantic-receipt-")
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "semantic-receipt-integration",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {"enabled": False},
        }), encoding="utf-8")
        env = {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
            "INTENT_TRANSLATOR_CONTROL_DB": str(root / "control.db"),
            "INTENT_TRANSLATOR_DATA_DIR": str(root / "receipts"),
            "INTENT_TRANSLATOR_SKILL_ROOTS": str(REPO_ROOT / "skills"),
            "INTENT_TRANSLATOR_ACTOR": "",
            "INTENT_TRANSLATOR_RECEIPT_SECRET": "",
            "INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS": "",
        }
        env_patch = patch.dict(os.environ, env, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        reset_receipt_state()
        self.addCleanup(reset_receipt_state)

    def test_prepared_actor_receipt_survives_semantic_clarify_and_revoke(self):
        for status in ("clarify", "revoke"):
            with self.subTest(status=status):
                compiler = IntentCompiler(
                    registry={"skills": [], "errors": []},
                    semantic_adapter=VetoAdapter(status),
                )
                with patch.object(server, "compiler", return_value=compiler):
                    initial = CompileRequest(
                        utterance=ACTION,
                        actor=ACTOR,
                        scope=f"{self.id()}:{status}",
                        semantic_mode="off",
                        include_prompt=False,
                        include_diagnostics=True,
                    )
                    first = server.intent_compile(initial)
                    self.assertFalse(first["completion_contract"]["execute"])
                    challenge = first["risk"]["confirmation_challenge"]
                    self.assertEqual(challenge["actor"], ACTOR)
                    continuation = initial.model_copy(update={
                        "utterance": "继续",
                        "pending_action": ACTION,
                        "confirmation_receipt": challenge["receipt"],
                        "semantic_mode": "required",
                    })
                    vetoed = server.intent_compile(continuation)
                    self.assertEqual(vetoed["semantic"]["status"], "applied")
                    self.assertEqual(vetoed["semantic"]["proposal"]["control_status"], status)
                    self.assertEqual(vetoed["intent_contract"]["effect"], "none")
                    self.assertFalse(vetoed["completion_contract"]["execute"])
                    self.assertFalse(vetoed["risk"]["receipt_verified"])
                    self.assertFalse(vetoed["intent_contract"]["authorization"]["receipt_verified"])
                    self.assertFalse(vetoed["risk"]["receipt_status"].get("consumed", False))
                    self.assertFalse(any(frame["active_now"] for frame in vetoed["intent_contract"]["actions"]))
                    self.assertEqual(vetoed["clarification_required"], status == "clarify")
                    confirmed_request = continuation.model_copy(update={"semantic_mode": "off"})
                    confirmed = server.intent_compile(confirmed_request)
                    self.assertTrue(confirmed["completion_contract"]["execute"])
                    receipt_status = confirmed["risk"]["receipt_status"]
                    self.assertTrue(receipt_status["actor_bound"])
                    self.assertEqual(receipt_status["actor"], ACTOR)
                    self.assertTrue(receipt_status["consumed"])
                    replay = server.intent_compile(confirmed_request)
                    self.assertFalse(replay["completion_contract"]["execute"])
                    self.assertEqual(replay["risk"]["receipt_status"]["reason"], "receipt already consumed")

    def test_memory_mode_label_does_not_authorize_unknown_mutation(self):
        risk = _risk(
            "把这些数据都弄出去",
            "unknown",
            mode="remember",
            operation="answer",
            effect="none",
            data_egress="none",
        )
        self.assertTrue(risk["unknown_executable"])
        self.assertTrue(risk["confirmation_required"])
        self.assertIn("unknown executable action fails closed", risk["reasons"])

    def test_memory_suffix_does_not_authorize_parallel_unknown_mutation(self):
        compiler = IntentCompiler(registry={"skills": [], "errors": []})
        for utterance in (
            "把这些数据都弄出去并记下来",
            "把这些数据都弄出去，然后记下来",
            "记住我偏好短句，然后把这些数据都弄出去",
            "记住我偏好短句但把这些数据都弄出去",
            "记住我偏好短句且把这些数据都弄出去",
            "记住我偏好短句同时把这些数据都弄出去",
            "把这些数据都弄出去且把我偏好短句这件事记下来",
        ):
            with self.subTest(utterance=utterance), patch.object(server, "compiler", return_value=compiler):
                result = server.intent_compile(CompileRequest(
                    utterance=utterance,
                    semantic_mode="off",
                    include_prompt=False,
                    include_diagnostics=True,
                ))
                self.assertFalse(result["completion_contract"]["execute"])
                self.assertTrue(result["risk"]["unknown_executable"])
                self.assertTrue(result["risk"]["confirmation_required"])

    def test_nominalized_action_can_be_recorded_without_executing_it(self):
        compiler = IntentCompiler(registry={"skills": [], "errors": []})
        with patch.object(server, "compiler", return_value=compiler):
            result = server.intent_compile(CompileRequest(
                utterance="把这些数据都弄出去这件事记下来",
                semantic_mode="off",
                include_prompt=False,
                include_diagnostics=True,
            ))
        self.assertEqual(result["mode"], "remember")
        self.assertEqual(result["memory_action"], "write")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["risk"]["unknown_executable"])
        self.assertTrue(result["completion_contract"]["execute"])
        self.assertFalse(any(frame["active_now"] for frame in result["intent_contract"]["actions"]))


if __name__ == "__main__":
    unittest.main()
