#!/usr/bin/env python3
"""Regression tests for the governed self-improvement lifecycle."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from learning_lifecycle import (
    capture_signal,
    lifecycle_stats,
    maintain_tiers,
    promote_signal,
    reinforce_memory,
)
from memory_store import add_memory, connect


class LearningLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "memory.db"
        self.connection = connect(self.db_path)

    def tearDown(self) -> None:
        self.connection.close()
        self.tempdir.cleanup()

    def test_capture_deduplicates_candidate_signals(self) -> None:
        first = capture_signal(
            self.connection,
            scope="project:test",
            signal_type="failure",
            summary="Skill lookup confused a display name with its slug.",
            evidence="Observed during registry lookup.",
        )
        second = capture_signal(
            self.connection,
            scope="project:test",
            signal_type="failure",
            summary="Skill lookup confused a display name with its slug.",
            evidence="The same failure recurred.",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["occurrence_count"], 2)
        self.assertTrue(second["source_fix_candidate"])
        self.assertEqual(
            second["recommended_action"],
            "diagnose-source-and-add-regression-before-archiving",
        )

    def test_promotion_requires_exact_confirmation_and_preserves_governance(self) -> None:
        signal = capture_signal(
            self.connection,
            scope="global",
            signal_type="preference",
            summary="Lead with the result.",
        )
        with self.assertRaises(ValueError):
            promote_signal(
                self.connection,
                signal_id=signal["id"],
                kind="preference",
                confirmation="",
            )
        promoted = promote_signal(
            self.connection,
            signal_id=signal["id"],
            kind="preference",
            confirmation=f"PROMOTE:{signal['id']}",
        )
        self.assertEqual(promoted["signal"]["status"], "promoted")
        self.assertEqual(promoted["memory"]["source_type"], "user_confirmed")
        self.assertEqual(promoted["memory"]["trust_level"], "trusted")
        reinforced = reinforce_memory(
            self.connection, memory_id=promoted["memory"]["id"], outcome="helpful"
        )
        self.assertEqual(reinforced["tier"], "hot")

    def test_reinforcement_changes_tier_but_not_authority(self) -> None:
        memory = add_memory(
            self.connection,
            kind="fact",
            scope="project:test",
            text="A tentative implementation observation.",
            confidence="observed",
            source_type="agent_inferred",
        )
        reinforce_memory(self.connection, memory_id=memory["id"], outcome="helpful")
        reinforced = reinforce_memory(
            self.connection, memory_id=memory["id"], outcome="helpful"
        )
        self.assertEqual(reinforced["tier"], "hot")
        self.assertEqual(reinforced["confidence"], "observed")
        self.assertEqual(reinforced["trust_level"], "untrusted")

    def test_maintenance_demotes_stale_memory_and_stats_report_lifecycle(self) -> None:
        memory = add_memory(
            self.connection,
            kind="fact",
            scope="project:test",
            text="A time-sensitive tool capability.",
            confidence="observed",
            source_type="agent_inferred",
            stale_after_days=1,
        )
        old = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
        self.connection.execute(
            "UPDATE memories SET updated_at = ?, tier = 'hot' WHERE id = ?",
            (old, memory["id"]),
        )
        self.connection.commit()
        result = maintain_tiers(self.connection, scope="project:test", apply=True)
        self.assertEqual(result["changed"], 1)
        repeated = maintain_tiers(self.connection, scope="project:test", apply=True)
        self.assertEqual(repeated["changed"], 0)
        tier = self.connection.execute(
            "SELECT tier FROM memories WHERE id = ?", (memory["id"],)
        ).fetchone()[0]
        self.assertEqual(tier, "cold")
        stats = lifecycle_stats(self.connection, scope="project:test")
        self.assertEqual(stats["memories_by_tier"]["cold"], 1)


if __name__ == "__main__":
    unittest.main()
