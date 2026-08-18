import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.control_plane import (  # noqa: E402
    ClaimLevel,
    ControlPlane,
    ControlState,
    ExecutionEnvelope,
    ExecutionEvidence,
)


def envelope(**overrides):
    values = {
        "goal_id": "goal-beta-b1",
        "task_id": "task-beta-b1",
        "dedupe_key": "beta-b1-single-writer",
        "frame_id": "frame-1",
        "object": "local beta candidate",
        "operation": "change",
        "effect": "write_local",
        "destination": "D:/test/intent-translator-beta-p0",
        "data_class": "internal",
        "authorization_id": "auth-beta-b1",
        "owner_thread": "writer-a",
        "generation": 1,
        "provenance": ["user-confirmed-next-gate"],
        "claim_level": ClaimLevel.READ_ONLY_FORM,
        "state": ControlState.ADMITTED,
        "reason_code": "NEW_REQUEST",
    }
    values.update(overrides)
    return ExecutionEnvelope(**values)


class B1ControlPlaneTests(unittest.TestCase):
    def test_envelope_rejects_missing_execution_identity(self):
        values = envelope().model_dump()
        values.pop("destination")
        with self.assertRaises(ValidationError):
            ExecutionEnvelope(**values)

    def test_two_concurrent_writers_only_admit_one_owner(self):
        plane = ControlPlane()
        barrier = threading.Barrier(3)
        decisions = []

        def contend(owner):
            barrier.wait()
            decisions.append(plane.admit(envelope(owner_thread=owner)))

        threads = [
            threading.Thread(target=contend, args=("writer-a",)),
            threading.Thread(target=contend, args=("writer-b",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        admitted = [item for item in decisions if item.admitted]
        rejected = [item for item in decisions if not item.admitted]
        self.assertEqual(len(admitted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].reason_code, "OWNER_CONFLICT")

    def test_old_generation_and_fence_are_rejected(self):
        plane = ControlPlane()
        first = plane.admit(envelope())
        replaced = plane.invalidate(
            first,
            reason_code="USER_REPLACED_ACTION",
            next_action="review replacement",
        )

        stale = plane.admit(envelope(), lease=first.lease)
        self.assertFalse(stale.admitted)
        self.assertFalse(stale.execute)
        self.assertEqual(stale.reason_code, "FENCE_MISMATCH")
        self.assertEqual(replaced.envelope.generation, 2)

    def test_crash_resume_increments_generation_and_requires_review(self):
        plane = ControlPlane()
        running = plane.admit(envelope())

        resumed = plane.resume(running.snapshot())

        self.assertFalse(resumed.admitted)
        self.assertFalse(resumed.execute)
        self.assertEqual(resumed.state, ControlState.VERIFYING)
        self.assertEqual(resumed.reason_code, "RECOVERY_REVIEW_REQUIRED")
        self.assertEqual(resumed.envelope.generation, 2)
        self.assertIsNone(resumed.lease)

    def test_expired_lease_does_not_auto_transfer_owner(self):
        now = datetime(2026, 8, 18, tzinfo=timezone.utc)
        plane = ControlPlane(clock=lambda: now)
        first = plane.admit(envelope(), lease_ttl_seconds=30)
        now += timedelta(seconds=31)

        takeover = plane.admit(envelope(owner_thread="writer-b"))

        self.assertFalse(takeover.admitted)
        self.assertFalse(takeover.execute)
        self.assertEqual(takeover.state, ControlState.EXPIRED)
        self.assertEqual(takeover.reason_code, "LEASE_EXPIRED_REVIEW_REQUIRED")

    def test_valid_owner_heartbeat_renews_visible_lease_time(self):
        now = datetime(2026, 8, 18, tzinfo=timezone.utc)
        plane = ControlPlane(clock=lambda: now)
        first = plane.admit(envelope(), lease_ttl_seconds=30)
        now += timedelta(seconds=10)

        heartbeat = plane.admit(
            envelope(),
            lease=first.lease,
            lease_ttl_seconds=30,
        )

        self.assertTrue(heartbeat.admitted)
        self.assertEqual(heartbeat.lease.last_heartbeat, now)
        self.assertGreater(heartbeat.lease.expires_at, first.lease.expires_at)

    def test_one_send_claim_is_bound_and_single_use(self):
        plane = ControlPlane()
        admitted = plane.admit(envelope())
        token = plane.issue_claim(admitted, ClaimLevel.ONE_SEND_AUTHORIZED)

        first = plane.admit(envelope(), lease=admitted.lease, claim=token)
        replay = plane.admit(envelope(), lease=admitted.lease, claim=token)

        self.assertTrue(first.execute)
        self.assertEqual(first.claim_level, ClaimLevel.ONE_SEND_AUTHORIZED)
        self.assertFalse(replay.execute)
        self.assertEqual(replay.reason_code, "CLAIM_REPLAYED")

    def test_claim_rejects_scope_object_destination_and_generation_drift(self):
        mutations = (
            {"task_id": "other-task"},
            {"object": "other object"},
            {"destination": "D:/other"},
            {"authorization_id": "other-authorization"},
            {"generation": 2},
            {"cannot_prove": ["new unresolved evidence gap"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                plane = ControlPlane()
                admitted = plane.admit(envelope())
                token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
                changed = plane.admit(
                    envelope(**mutation),
                    lease=admitted.lease,
                    claim=token,
                )
                self.assertFalse(changed.execute)
                self.assertIn(changed.reason_code, {"CLAIM_BINDING_MISMATCH", "FENCE_MISMATCH"})

    def test_cannot_prove_and_incomplete_evidence_cannot_complete(self):
        plane = ControlPlane()
        admitted = plane.admit(envelope())
        token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
        executing = plane.admit(envelope(), lease=admitted.lease, claim=token)

        incomplete = plane.record(
            executing,
            ExecutionEvidence(
                command="python -m unittest",
                session="session-1",
                pid=1234,
                artifact="D:/test/result.json",
                true_exit=0,
                cannot_prove=["artifact sha missing"],
            ),
        )

        self.assertEqual(incomplete.state, ControlState.EVIDENCE_MISSING)
        self.assertFalse(incomplete.completed)
        self.assertEqual(incomplete.reason_code, "CANNOT_PROVE_PRESENT")

    def test_envelope_cannot_prove_cannot_become_completed(self):
        plane = ControlPlane()
        unresolved = envelope(cannot_prove=["host enforcement not verified"])
        admitted = plane.admit(unresolved)
        token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
        executing = plane.admit(unresolved, lease=admitted.lease, claim=token)

        result = plane.record(
            executing,
            ExecutionEvidence(
                command="python -m unittest",
                session="session-1",
                pid=1234,
                artifact="D:/test/result.json",
                artifact_sha256="a" * 64,
                true_exit=0,
            ),
        )

        self.assertFalse(result.completed)
        self.assertEqual(result.state, ControlState.EVIDENCE_MISSING)
        self.assertEqual(result.reason_code, "CANNOT_PROVE_PRESENT")

    def test_verified_evidence_completes_with_traceable_fields(self):
        plane = ControlPlane()
        admitted = plane.admit(envelope())
        token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
        executing = plane.admit(envelope(), lease=admitted.lease, claim=token)
        evidence = ExecutionEvidence(
            command="python -m unittest",
            session="session-1",
            pid=1234,
            artifact="D:/test/result.json",
            artifact_sha256="a" * 64,
            true_exit=0,
        )

        completed = plane.record(executing, evidence)

        self.assertTrue(completed.completed)
        self.assertEqual(completed.state, ControlState.COMPLETED)
        self.assertEqual(completed.evidence, evidence)

    def test_shared_registry_allows_only_one_owner_across_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "control-plane.db"
            plane_a = ControlPlane(state_path=state_path)
            plane_b = ControlPlane(state_path=state_path)
            barrier = threading.Barrier(3)
            decisions = []

            def contend(plane, owner):
                barrier.wait()
                decisions.append(plane.admit(envelope(owner_thread=owner)))

            threads = [
                threading.Thread(target=contend, args=(plane_a, "writer-a")),
                threading.Thread(target=contend, args=(plane_b, "writer-b")),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

        self.assertEqual(sum(item.admitted for item in decisions), 1)
        self.assertEqual(sum(item.reason_code == "OWNER_CONFLICT" for item in decisions), 1)

    def test_late_evidence_from_invalidated_writer_is_rejected(self):
        plane = ControlPlane()
        admitted = plane.admit(envelope())
        token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
        executing = plane.admit(envelope(), lease=admitted.lease, claim=token)
        plane.invalidate(
            executing,
            reason_code="USER_REPLACED_ACTION",
            next_action="review replacement",
        )

        late = plane.record(
            executing,
            ExecutionEvidence(
                command="python -m unittest",
                session="session-old",
                pid=1234,
                artifact="D:/test/result.json",
                artifact_sha256="a" * 64,
                true_exit=0,
            ),
        )

        self.assertFalse(late.completed)
        self.assertEqual(late.state, ControlState.FENCE_MISMATCH)
        self.assertEqual(late.reason_code, "LATE_EVIDENCE_REJECTED")

    def test_completed_task_cannot_be_reopened_with_another_claim(self):
        plane = ControlPlane()
        admitted = plane.admit(envelope())
        token = plane.issue_claim(admitted, ClaimLevel.EXECUTION_AUTHORIZED)
        executing = plane.admit(envelope(), lease=admitted.lease, claim=token)
        completed = plane.record(
            executing,
            ExecutionEvidence(
                command="python -m unittest",
                session="session-1",
                pid=1234,
                artifact="D:/test/result.json",
                artifact_sha256="a" * 64,
                true_exit=0,
            ),
        )

        reopened = plane.admit(envelope(), lease=completed.lease)

        self.assertFalse(reopened.admitted)
        self.assertFalse(reopened.execute)
        self.assertEqual(reopened.reason_code, "TERMINAL_STATE")

    def test_stale_recovery_snapshot_cannot_advance_generation_twice(self):
        plane = ControlPlane()
        running = plane.admit(envelope())
        snapshot = running.snapshot()
        first = plane.resume(snapshot)

        replay = plane.resume(snapshot)

        self.assertFalse(replay.admitted)
        self.assertEqual(replay.state, ControlState.FENCE_MISMATCH)
        self.assertEqual(replay.reason_code, "STALE_SNAPSHOT")
        self.assertEqual(replay.envelope.generation, first.envelope.generation)

    def test_stale_owner_cannot_invalidate_the_new_generation(self):
        plane = ControlPlane()
        running = plane.admit(envelope())
        current = plane.invalidate(
            running,
            reason_code="USER_REPLACED_ACTION",
            next_action="review replacement",
        )

        stale = plane.invalidate(
            running,
            reason_code="OLD_OWNER_CANCELLED",
            next_action="stop",
        )

        self.assertFalse(stale.admitted)
        self.assertEqual(stale.state, ControlState.FENCE_MISMATCH)
        self.assertEqual(stale.reason_code, "STALE_INVALIDATION")
        self.assertEqual(stale.envelope.generation, current.envelope.generation)


if __name__ == "__main__":
    unittest.main()
