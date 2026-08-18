import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.models import (  # noqa: E402
    CompileRequest,
    ControlIdentity,
    ControlRecordRequest,
    ControlResumeRequest,
)
from intent_translator_mcp.server import (  # noqa: E402
    intent_compile,
    intent_control_record,
    intent_control_resume,
)


class McpControlPlaneTests(unittest.TestCase):
    def _env(self, root: Path) -> dict[str, str]:
        return {
            "INTENT_TRANSLATOR_PROFILE": str(root / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_CONTROL_DB": str(root / "control.db"),
        }

    def test_local_action_is_admitted_and_complete_evidence_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-mcp-b1",
                            task_id="task-mcp-b1",
                            dedupe_key="mcp-b1-local-action",
                            frame_id="frame-mcp-b1",
                            owner_thread="writer-mcp-b1",
                            generation=1,
                            required_artifacts=["test-report"],
                        ),
                    )
                )

                self.assertTrue(compiled["control"]["admitted"])
                self.assertTrue(compiled["control"]["execute"])
                self.assertEqual(compiled["control"]["claim_level"], "ACTION_AUTHORIZED")
                self.assertEqual(compiled["control"]["enforcement_scope"], "intent-mcp-path-only")

                recorded = intent_control_record(
                    ControlRecordRequest(
                        admission_receipt=compiled["control"]["admission_receipt"],
                        command="python -m unittest",
                        session="codex-session-1",
                        pid=1234,
                        artifact=str(root / "test-report.json"),
                        artifact_sha256="a" * 64,
                        true_exit=0,
                    )
                )

            self.assertTrue(recorded["completed"])
            self.assertEqual(recorded["state"], "COMPLETED")
            self.assertEqual(recorded["reason_code"], "EVIDENCE_VERIFIED")

    def test_same_dedupe_key_admits_only_one_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                first = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-owner",
                            task_id="task-owner",
                            dedupe_key="one-owner-only",
                            frame_id="frame-owner",
                            owner_thread="writer-a",
                            generation=1,
                        ),
                    )
                )
                second = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-owner",
                            task_id="task-owner",
                            dedupe_key="one-owner-only",
                            frame_id="frame-owner",
                            owner_thread="writer-b",
                            generation=1,
                        ),
                    )
                )

            self.assertTrue(first["control"]["execute"])
            self.assertFalse(second["control"]["admitted"])
            self.assertFalse(second["control"]["execute"])
            self.assertEqual(second["control"]["reason_code"], "OWNER_CONFLICT")
            self.assertNotIn("admission_receipt", second["control"])

    def test_untrusted_granted_hint_cannot_authorize_external_send(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="把这个发到 GitHub 上",
                        authorization="granted",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-external",
                            task_id="task-external",
                            dedupe_key="external-needs-receipt",
                            frame_id="frame-external",
                            owner_thread="writer-external",
                            generation=1,
                        ),
                    )
                )

            self.assertTrue(compiled["control"]["admitted"])
            self.assertFalse(compiled["control"]["execute"])
            self.assertEqual(compiled["control"]["state"], "WAITING_AUTH")
            self.assertEqual(compiled["control"]["claim_level"], "READ_ONLY_FORM")
            self.assertEqual(compiled["control"]["envelope"]["authorization_id"], "ungranted")
            self.assertEqual(compiled["tool_gateway"]["decision"], "human_review")

    def test_exact_confirmation_upgrades_only_the_bound_external_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                proposed = intent_compile(
                    CompileRequest(
                        utterance="把这个发到 GitHub 上",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-confirm",
                            task_id="task-confirm",
                            dedupe_key="external-confirmed-once",
                            frame_id="frame-confirm",
                            owner_thread="writer-confirm",
                            generation=1,
                        ),
                    )
                )
                confirmed = intent_compile(
                    CompileRequest(
                        utterance="确认",
                        pending_action="把这个发到 GitHub 上",
                        confirmation_receipt=proposed["risk"]["confirmation_challenge"]["receipt"],
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-confirm",
                            task_id="task-confirm",
                            dedupe_key="external-confirmed-once",
                            frame_id="frame-confirm",
                            owner_thread="writer-confirm",
                            generation=1,
                            continuation_receipt=proposed["control"]["admission_receipt"],
                        ),
                    )
                )

            self.assertFalse(proposed["control"]["execute"])
            self.assertTrue(confirmed["risk"]["receipt_verified"])
            self.assertTrue(confirmed["control"]["execute"])
            self.assertEqual(confirmed["control"]["claim_level"], "ONE_SEND_AUTHORIZED")
            self.assertTrue(
                confirmed["control"]["envelope"]["authorization_id"].startswith("confirmation:")
            )

    def test_tampered_admission_receipt_cannot_record_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-tamper",
                            task_id="task-tamper",
                            dedupe_key="tampered-receipt",
                            frame_id="frame-tamper",
                            owner_thread="writer-tamper",
                            generation=1,
                        ),
                    )
                )
                receipt = compiled["control"]["admission_receipt"]
                tampered = receipt[:-1] + ("A" if receipt[-1] != "A" else "B")

                with self.assertRaisesRegex(ValueError, "control receipt is invalid"):
                    intent_control_record(
                        ControlRecordRequest(
                            admission_receipt=tampered,
                            command="python -m unittest",
                            session="codex-session-1",
                            pid=1234,
                            artifact=str(root / "report.json"),
                            artifact_sha256="a" * 64,
                            true_exit=0,
                        )
                    )

    def test_incomplete_evidence_cannot_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-evidence",
                            task_id="task-evidence",
                            dedupe_key="evidence-required",
                            frame_id="frame-evidence",
                            owner_thread="writer-evidence",
                            generation=1,
                        ),
                    )
                )
                recorded = intent_control_record(
                    ControlRecordRequest(
                        admission_receipt=compiled["control"]["admission_receipt"],
                        command="python -m unittest",
                        session="codex-session-1",
                        pid=1234,
                        artifact=str(root / "report.json"),
                        true_exit=0,
                    )
                )

            self.assertFalse(recorded["completed"])
            self.assertEqual(recorded["state"], "EVIDENCE_MISSING")
            self.assertEqual(recorded["reason_code"], "EVIDENCE_FIELDS_MISSING")

    def test_resume_fences_old_owner_and_rejects_late_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                compiled = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-resume",
                            task_id="task-resume",
                            dedupe_key="resume-fences-old-owner",
                            frame_id="frame-resume",
                            owner_thread="writer-old",
                            generation=1,
                        ),
                    )
                )
                resumed = intent_control_resume(
                    ControlResumeRequest(
                        resume_receipt=compiled["control"]["resume_receipt"]
                    )
                )
                late = intent_control_record(
                    ControlRecordRequest(
                        admission_receipt=compiled["control"]["admission_receipt"],
                        command="python -m unittest",
                        session="codex-session-old",
                        pid=1234,
                        artifact=str(root / "report.json"),
                        artifact_sha256="a" * 64,
                        true_exit=0,
                    )
                )

            self.assertFalse(resumed["execute"])
            self.assertEqual(resumed["state"], "VERIFYING")
            self.assertEqual(resumed["envelope"]["generation"], 2)
            self.assertEqual(resumed["reason_code"], "RECOVERY_REVIEW_REQUIRED")
            self.assertFalse(late["completed"])
            self.assertEqual(late["reason_code"], "LATE_EVIDENCE_REJECTED")

    def test_continuation_receipt_rejects_action_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, self._env(root), clear=False):
                first = intent_compile(
                    CompileRequest(
                        utterance="在本地项目中运行单元测试",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-drift",
                            task_id="task-drift",
                            dedupe_key="action-drift",
                            frame_id="frame-drift",
                            owner_thread="writer-drift",
                            generation=1,
                        ),
                    )
                )
                changed = intent_compile(
                    CompileRequest(
                        utterance="删除这个本地文件",
                        semantic_mode="off",
                        include_prompt=False,
                        control=ControlIdentity(
                            goal_id="goal-drift",
                            task_id="task-drift",
                            dedupe_key="action-drift",
                            frame_id="frame-drift",
                            owner_thread="writer-drift",
                            generation=1,
                            continuation_receipt=first["control"]["admission_receipt"],
                        ),
                    )
                )

            self.assertFalse(changed["control"]["admitted"])
            self.assertFalse(changed["control"]["execute"])
            self.assertEqual(
                changed["control"]["reason_code"], "CONTINUATION_BINDING_MISMATCH"
            )


if __name__ == "__main__":
    unittest.main()
