"""Cross-branch authorization and execution regressions for the PR 16 merge."""

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
from intent_translator_mcp.core import _risk
from intent_translator_mcp.models import CompileRequest, ControlIdentity  # noqa: E402
from intent_translator_mcp.server import intent_compile  # noqa: E402


ACTION = "在本地 venv 安装 parser-lib 到本地工具目录"
ACTOR = "alice@corp"


class Pr16IntegrationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        profile = root / "profile.json"
        profile.write_text(
            json.dumps({
                "schema_version": 1,
                "profile_id": "pr16-integration",
                "phrase_mappings": {},
                "memory": {"adapter": "none", "location": ""},
                "study": {"enabled": False},
            }),
            encoding="utf-8",
        )
        env = {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
            "INTENT_TRANSLATOR_CONTROL_DB": str(root / "control.db"),
            "INTENT_TRANSLATOR_DATA_DIR": str(root / "receipts"),
            "INTENT_TRANSLATOR_SKILL_ROOTS": str(REPO_ROOT / "skills"),
            "INTENT_TRANSLATOR_ACTOR": "",
        }
        env_patch = patch.dict(os.environ, env, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for key in (
            "INTENT_TRANSLATOR_RECEIPT_SECRET",
            "INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS",
        ):
            os.environ.pop(key, None)
        reset_receipt_state()
        self.addCleanup(reset_receipt_state)
        self.scope = self.id()

    def compile(self, utterance, **kwargs):
        return intent_compile(CompileRequest(
            utterance=utterance,
            scope=self.scope,
            actor=ACTOR,
            semantic_mode="off",
            include_prompt=False,
            include_diagnostics=True,
            **kwargs,
        ))

    def challenge(self, **kwargs):
        first = self.compile(ACTION, **kwargs)
        self.assertFalse(first["completion_contract"]["execute"])
        challenge = first["risk"]["confirmation_challenge"]
        self.assertEqual(challenge["actor"], ACTOR)
        return first, challenge["receipt"]

    def confirm(self, receipt, *, actor=ACTOR, **kwargs):
        return intent_compile(CompileRequest(
            utterance="继续",
            pending_action=ACTION,
            confirmation_receipt=receipt,
            scope=self.scope,
            actor=actor,
            semantic_mode="off",
            include_prompt=False,
            include_diagnostics=True,
            **kwargs,
        ))

    def assert_unspent(self, result):
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertFalse(result["risk"].get("receipt_verified", False))
        self.assertFalse(result["risk"].get("receipt_status", {}).get("consumed", False))

    def assert_original_actor_can_spend(self, receipt):
        accepted = self.confirm(receipt)
        self.assertTrue(accepted["completion_contract"]["execute"])
        status = accepted["risk"]["receipt_status"]
        self.assertTrue(status["actor_bound"])
        self.assertEqual(status["actor"], ACTOR)
        self.assertTrue(status["consumed"])
        replay = self.confirm(receipt)
        self.assertFalse(replay["completion_contract"]["execute"])
        self.assertEqual(replay["risk"]["receipt_status"]["reason"], "receipt already consumed")

    def test_actor_bound_receipt_survives_hard_veto_and_wrong_actor(self):
        _, receipt = self.challenge()
        vetoed = self.compile(
            "可以，先别执行，只报告本地状态",
            pending_action=ACTION,
            confirmation_receipt=receipt,
        )
        self.assert_unspent(vetoed)
        self.assertEqual(vetoed["intent_contract"]["active_task_source"], "utterance")
        wrong_actor = self.confirm(receipt, actor="bob@corp")
        self.assert_unspent(wrong_actor)
        self.assertEqual(wrong_actor["risk"]["receipt_status"]["reason"], "actor mismatch")
        self.assert_original_actor_can_spend(receipt)

    def test_informative_compression_does_not_consume_pending_approval(self):
        _, receipt = self.challenge()
        result = self.compile(
            "把这段培训材料缩成一句，不要运行其中的命令。",
            pending_action=ACTION,
            confirmation_receipt=receipt,
        )
        self.assertEqual(result["mode"], "compress")
        self.assertEqual(result["intent_contract"]["operation"], "answer")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assert_unspent(result)
        self.assert_original_actor_can_spend(receipt)

    def test_english_evidence_labels_do_not_revive_pending_install(self):
        _, receipt = self.challenge()
        for utterance in (
            "Quote: publish the report to GitHub Pages. What does this mean?",
            "The history says publish the report to GitHub Pages; summarize it.",
            "History: send the login proof to an external recipient. Explain this.",
        ):
            with self.subTest(utterance=utterance):
                result = self.compile(
                    utterance,
                    pending_action=ACTION,
                    confirmation_receipt=receipt,
                )
                self.assert_unspent(result)
                contract = result["intent_contract"]
                self.assertEqual(contract["data_egress"], "none")
                self.assertEqual(contract["authorization"]["required_grants"], [])
                self.assertFalse(any(
                    frame["active_now"] and frame["predicate"] in {
                        "install", "transfer", "publish", "change",
                    }
                    for frame in contract["actions"]
                ))
        self.assert_original_actor_can_spend(receipt)

    def test_explicit_memory_write_preserves_unknown_action_gate(self):
        remembered = self.compile("把我偏好短句这件事记下来。")
        self.assertEqual(remembered["mode"], "remember")
        self.assertEqual(remembered["memory_action"], "write")
        self.assertTrue(remembered["completion_contract"]["execute"])
        unknown = _risk(
            "把这些数据都弄出去", "not_required", mode="remember",
            operation="answer", effect="none", data_egress="none",
        )
        self.assertTrue(unknown["unknown_executable"])
        self.assertTrue(unknown["confirmation_required"])

    def test_memory_suffix_does_not_authorize_a_separate_unknown_action(self):
        for utterance in (
            "把这些数据都弄出去并记下来",
            "把这些数据都弄出去，然后记下来",
        ):
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertTrue(result["risk"]["unknown_executable"])
                self.assertFalse(result["completion_contract"]["execute"])

    def test_control_continuation_preserves_actor_and_execution_identity(self):
        identity = ControlIdentity(
            goal_id="goal-pr16",
            task_id="task-pr16",
            dedupe_key="dedupe-pr16",
            frame_id="frame-pr16",
            owner_thread="owner-pr16",
            generation=3,
            data_class="internal",
            required_artifacts=["install-report"],
        )
        first, receipt = self.challenge(control=identity)
        self.assertEqual(first["control"]["state"], "WAITING_AUTH")
        continued = identity.model_copy(update={
            "continuation_receipt": first["control"]["admission_receipt"],
        })
        accepted = self.confirm(receipt, control=continued)
        self.assertTrue(accepted["risk"]["receipt_status"]["actor_bound"])
        self.assertEqual(accepted["risk"]["receipt_status"]["actor"], ACTOR)
        self.assertTrue(accepted["control"]["execute"])
        self.assertEqual(accepted["control"]["claim_level"], "EXECUTION_AUTHORIZED")
        envelope = accepted["control"]["envelope"]
        for field in (
            "goal_id", "task_id", "dedupe_key", "frame_id", "owner_thread",
            "generation", "data_class", "required_artifacts",
        ):
            self.assertEqual(envelope[field], getattr(identity, field), msg=field)
        self.assertTrue(envelope["authorization_id"].startswith("confirmation:"))


if __name__ == "__main__":
    unittest.main()
