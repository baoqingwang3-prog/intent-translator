"""Receipts must stay valid across processes and restarts without losing single use."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.authorization import (  # noqa: E402
    issue_confirmation_receipt,
    receipt_backend_status,
    reset_receipt_state,
    verify_confirmation_receipt,
)

ACTION = "把这个仓库发到 github 上"
SCOPE = "global"
GRANTS = ["external"]

VERIFY_IN_SUBPROCESS = """
import json, sys
sys.path.insert(0, {src!r})
from intent_translator_mcp.authorization import verify_confirmation_receipt
print(json.dumps(verify_confirmation_receipt(
    {receipt!r}, {action!r}, {scope!r},
    required_grants={grants!r}, consume={consume!r}, actor={actor!r},
)))
"""


class ReceiptDeploymentTests(unittest.TestCase):
    def setUp(self):
        self._original_env = {
            key: os.environ.get(key)
            for key in (
                "INTENT_TRANSLATOR_DATA_DIR",
                "INTENT_TRANSLATOR_RECEIPT_SECRET",
                "INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS",
            )
        }
        self._temp = tempfile.TemporaryDirectory()
        os.environ["INTENT_TRANSLATOR_DATA_DIR"] = self._temp.name
        for key in ("INTENT_TRANSLATOR_RECEIPT_SECRET", "INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS"):
            os.environ.pop(key, None)
        reset_receipt_state()

    def tearDown(self):
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_receipt_state()
        self._temp.cleanup()

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        env["INTENT_TRANSLATOR_DATA_DIR"] = os.environ["INTENT_TRANSLATOR_DATA_DIR"]
        for key in ("INTENT_TRANSLATOR_RECEIPT_SECRET", "INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS"):
            env.pop(key, None)
        return env

    def _verify_elsewhere(self, receipt: str, *, actor: str = "", consume: bool = False) -> dict:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                VERIFY_IN_SUBPROCESS.format(
                    src=str(REPO_ROOT / "src"),
                    receipt=receipt,
                    action=ACTION,
                    scope=SCOPE,
                    grants=GRANTS,
                    consume=consume,
                    actor=actor,
                ),
            ],
            capture_output=True,
            text=True,
            env=self._subprocess_env(),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_a_shared_data_directory_reports_a_shared_backend(self):
        status = receipt_backend_status()
        self.assertEqual(status["key_source"], "shared-key-file")
        self.assertTrue(status["shared_across_processes"])
        self.assertTrue(status["survives_restart"])
        self.assertEqual(status["warning"], "")

    def test_a_receipt_issued_here_verifies_in_another_process(self):
        receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
        self.assertTrue(self._verify_elsewhere(receipt)["verified"])

    def test_single_use_is_enforced_across_processes(self):
        receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
        self.assertTrue(self._verify_elsewhere(receipt, consume=True)["verified"])
        replayed_elsewhere = self._verify_elsewhere(receipt, consume=True)
        self.assertFalse(replayed_elsewhere["verified"])
        self.assertEqual(replayed_elsewhere["reason"], "receipt already consumed")
        replayed_here = verify_confirmation_receipt(
            receipt, ACTION, SCOPE, required_grants=GRANTS, consume=True
        )
        self.assertFalse(replayed_here["verified"])
        self.assertEqual(replayed_here["reason"], "receipt already consumed")

    def test_a_receipt_is_bound_to_the_actor_that_approved_it(self):
        issued = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS, actor="alice@corp")
        self.assertEqual(issued["actor"], "alice@corp")
        impersonated = self._verify_elsewhere(issued["receipt"], actor="bob@corp")
        self.assertFalse(impersonated["verified"])
        self.assertEqual(impersonated["reason"], "actor mismatch")
        unattributed = self._verify_elsewhere(issued["receipt"])
        self.assertFalse(unattributed["verified"])
        self.assertEqual(unattributed["reason"], "actor mismatch")
        accepted = self._verify_elsewhere(issued["receipt"], actor="alice@corp")
        self.assertTrue(accepted["verified"])
        self.assertTrue(accepted["actor_bound"])

    def test_changing_the_action_still_invalidates_a_shared_receipt(self):
        receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
        result = verify_confirmation_receipt(
            receipt, "把这个仓库发到 gitlab 上", SCOPE, required_grants=GRANTS
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "action mismatch")

    def test_key_rotation_keeps_outstanding_receipts_valid_for_one_step(self):
        previous, current = secrets.token_bytes(32).hex(), secrets.token_bytes(32).hex()
        os.environ["INTENT_TRANSLATOR_RECEIPT_SECRET"] = previous
        reset_receipt_state()
        receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]

        os.environ["INTENT_TRANSLATOR_RECEIPT_SECRET"] = current
        os.environ["INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS"] = previous
        reset_receipt_state()
        self.assertEqual(receipt_backend_status()["verifiable_key_count"], 2)
        self.assertTrue(
            verify_confirmation_receipt(receipt, ACTION, SCOPE, required_grants=GRANTS)["verified"]
        )

        os.environ.pop("INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS")
        reset_receipt_state()
        retired = verify_confirmation_receipt(receipt, ACTION, SCOPE, required_grants=GRANTS)
        self.assertFalse(retired["verified"])
        self.assertEqual(retired["reason"], "invalid signature")

    def test_an_unusable_data_directory_degrades_loudly_instead_of_failing(self):
        os.environ["INTENT_TRANSLATOR_DATA_DIR"] = str(
            Path(self._temp.name) / "unwritable-file" / "nested"
        )
        Path(self._temp.name, "unwritable-file").write_text("not a directory", encoding="utf-8")
        reset_receipt_state()
        status = receipt_backend_status()
        self.assertEqual(status["key_source"], "process-local")
        self.assertFalse(status["shared_across_processes"])
        self.assertIn("process-local", status["warning"])
        receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
        self.assertTrue(
            verify_confirmation_receipt(receipt, ACTION, SCOPE, required_grants=GRANTS)["verified"]
        )

    def test_the_compiler_will_not_let_one_actor_spend_another_actors_approval(self):
        from intent_translator_mcp.core import IntentCompiler
        from intent_translator_mcp.models import CompileRequest

        root = Path(self._temp.name)
        os.environ["INTENT_TRANSLATOR_PROFILE"] = str(root / "profile.json")
        os.environ["INTENT_TRANSLATOR_MEMORY_DB"] = str(root / "memory.db")
        try:
            compiler = IntentCompiler(registry={"skills": [], "errors": []}, semantic_adapter=None)
            first = compiler.compile(
                CompileRequest(utterance=ACTION, actor="alice@corp", semantic_mode="off")
            )
            self.assertEqual(first["tool_gateway"]["decision"], "human_review")
            challenge = first["risk"]["confirmation_challenge"]
            self.assertEqual(challenge["actor"], "alice@corp")

            def confirm(actor: str) -> dict:
                return compiler.compile(
                    CompileRequest(
                        utterance="好",
                        pending_action=ACTION,
                        actor=actor,
                        confirmation_receipt=challenge["receipt"],
                        semantic_mode="off",
                    )
                )

            impersonated = confirm("bob@corp")
            self.assertEqual(impersonated["tool_gateway"]["decision"], "human_review")
            self.assertFalse(impersonated["completion_contract"]["execute"])
            self.assertEqual(impersonated["risk"]["receipt_status"]["reason"], "actor mismatch")

            approved = confirm("alice@corp")
            self.assertEqual(approved["tool_gateway"]["decision"], "allow")
            self.assertTrue(approved["completion_contract"]["execute"])
        finally:
            for key in ("INTENT_TRANSLATOR_PROFILE", "INTENT_TRANSLATOR_MEMORY_DB"):
                os.environ.pop(key, None)

    def test_receipts_work_in_an_environment_with_no_home_directory(self):
        with unittest.mock.patch.object(
            Path, "home", side_effect=RuntimeError("Could not determine home directory.")
        ):
            reset_receipt_state()
            status = receipt_backend_status()
            self.assertTrue(status["shared_across_processes"])
            receipt = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
            self.assertTrue(
                verify_confirmation_receipt(
                    receipt, ACTION, SCOPE, required_grants=GRANTS, consume=True
                )["verified"]
            )

            os.environ.pop("INTENT_TRANSLATOR_DATA_DIR")
            reset_receipt_state()
            homeless = receipt_backend_status()
            self.assertEqual(homeless["key_source"], "process-local")
            self.assertIn("process-local", homeless["warning"])
            fallback = issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)["receipt"]
            self.assertTrue(
                verify_confirmation_receipt(fallback, ACTION, SCOPE, required_grants=GRANTS)[
                    "verified"
                ]
            )

    def test_the_key_file_is_not_world_readable(self):
        issue_confirmation_receipt(ACTION, SCOPE, grants=GRANTS)
        key_path = Path(self._temp.name) / "receipt-key"
        self.assertTrue(key_path.is_file())
        if os.name != "nt":
            self.assertEqual(key_path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
