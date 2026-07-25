import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.config import generate_config  # noqa: E402
from intent_translator_mcp.core import _load_skill_script  # noqa: E402
from intent_translator_mcp.feedback import (  # noqa: E402
    export_feedback_candidates,
    review_feedback_candidate,
)
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.server import intent_compile  # noqa: E402
from intent_translator_mcp.trial import (  # noqa: E402
    init_trial,
    record_trial_event,
    summarize_trials,
)


class HostInvocationReceiptTests(unittest.TestCase):
    def test_generated_configs_name_the_host_and_compile_returns_a_bounded_receipt(self):
        for host in ("codex", "claude", "cursor"):
            self.assertIn("INTENT_TRANSLATOR_HOST", generate_config(host, "intent-translator-mcp"))
            self.assertIn(host, generate_config(host, "intent-translator-mcp"))

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_HOST": "cursor",
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
            clear=False,
        ):
            first = intent_compile(
                CompileRequest(utterance="Review the local architecture", semantic_mode="off", include_prompt=False)
            )
            second = intent_compile(
                CompileRequest(utterance="Review the local architecture", semantic_mode="off", include_prompt=False)
            )

        receipt = first["invocation_receipt"]
        self.assertTrue(receipt["preflight_observed"])
        self.assertEqual(receipt["host"], "cursor")
        self.assertEqual(receipt["decision"], first["tool_gateway"]["decision"])
        self.assertEqual(len(receipt["request_sha256"]), 64)
        self.assertNotEqual(receipt["receipt_id"], second["invocation_receipt"]["receipt_id"])
        self.assertEqual(receipt["request_sha256"], second["invocation_receipt"]["request_sha256"])
        self.assertEqual(receipt["enforcement_claim"], "preflight-observed-not-host-enforced")
        self.assertNotIn("Review the local architecture", json.dumps(receipt))


class FeedbackCandidateTests(unittest.TestCase):
    def test_execution_mismatch_exports_hash_only_until_human_review(self):
        memory = _load_skill_script("memory_store")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "memory.db"
            connection = memory.connect(db)
            try:
                memory.verify_execution_outcome(
                    connection,
                    scope="private-client-project",
                    utterance="Use Playwright to verify the private dashboard",
                    expected_goal="explain testing",
                    expected_operation="answer",
                    expected_skill="",
                    actual_goal="run browser test",
                    actual_operation="test",
                    actual_skill="browser",
                    success=False,
                    user_confirmed_correction=True,
                )
            finally:
                connection.close()

            exported = export_feedback_candidates(db, limit=10)
            candidate = exported["candidates"][0]
            reviewed = review_feedback_candidate(
                candidate,
                sanitized_utterance="Use Playwright to verify the local dashboard",
                expected={
                    "operation": "test",
                    "effect": "read_local",
                    "primary_skill": "browser",
                    "execute": True,
                },
                consent_to_publish=True,
            )

        serialized = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("private dashboard", serialized)
        self.assertNotIn("private-client-project", serialized)
        self.assertEqual(len(candidate["utterance_sha256"]), 64)
        self.assertEqual(candidate["status"], "needs-human-review")
        self.assertFalse(candidate["publishable"])
        self.assertEqual(reviewed["status"], "reviewed-fixture-candidate")
        self.assertTrue(reviewed["consent_to_publish"])
        self.assertEqual(reviewed["utterance"], "Use Playwright to verify the local dashboard")


class TrialEvidenceTests(unittest.TestCase):
    def test_trial_session_records_metrics_without_raw_utterances(self):
        with tempfile.TemporaryDirectory() as temp:
            session_path = Path(temp) / "participant.json"
            init_trial(session_path, real_participant=True, consent_confirmed=True)
            for event in ("install", "onboarding", "request", "correction", "receipt", "uninstall"):
                record_trial_event(
                    session_path,
                    event=event,
                    status="pass",
                    duration_seconds=12.5 if event == "install" else None,
                )
            summary = summarize_trials([session_path])
            payload = json.loads(session_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["participant_count"], 1)
        self.assertEqual(summary["completed_participant_count"], 1)
        self.assertEqual(summary["dangerous_confirmation_misses"], 0)
        self.assertEqual(summary["cross_profile_contamination"], 0)
        self.assertEqual(summary["creator_default_leakage"], 0)
        self.assertEqual(summary["evidence_class"], "real-user-self-reported-candidate")
        self.assertFalse(payload["privacy"]["raw_utterances_stored"])
        self.assertTrue(all("utterance" not in event for event in payload["events"]))
        self.assertNotIn("notes", payload)


if __name__ == "__main__":
    unittest.main()
