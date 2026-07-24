import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from memory_store import (  # noqa: E402
    add_correction,
    add_memory,
    check_intent,
    connect,
    list_memories,
    record_correction_outcome,
    search_corrections,
    search_memories,
)


class MemoryStoreTests(unittest.TestCase):
    def test_add_deduplicate_and_search_by_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                first = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="Prefer concise Chinese answers",
                    confidence="confirmed",
                )
                duplicate = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="Prefer concise Chinese answers",
                    confidence="observed",
                    source="conversation",
                )
                add_memory(
                    connection,
                    kind="decision",
                    scope="project-alpha",
                    text="Use SQLite for local memory",
                    confidence="confirmed",
                )
                add_memory(
                    connection,
                    kind="decision",
                    scope="project-beta",
                    text="Use Markdown for local memory",
                    confidence="confirmed",
                )

                self.assertFalse(first["deduplicated"])
                self.assertTrue(duplicate["deduplicated"])
                self.assertEqual(len(list_memories(connection)), 3)

                results = search_memories(
                    connection, query="SQLite memory", scope="project-alpha", limit=5
                )
                self.assertEqual([item["scope"] for item in results], ["project-alpha"])
                global_results = search_memories(
                    connection, query="concise Chinese", scope="project-alpha", limit=5
                )
                self.assertEqual(global_results[0]["scope"], "global")
            finally:
                connection.close()

    def test_rejects_unknown_confidence(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                with self.assertRaises(ValueError):
                    add_memory(
                        connection,
                        kind="preference",
                        scope="global",
                        text="Example",
                        confidence="certain",
                    )
            finally:
                connection.close()

    def test_stale_memory_is_flagged_and_ranked_below_fresh_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                stale = add_memory(
                    connection,
                    kind="fact",
                    scope="project-alpha",
                    text="The deployment target is staging",
                    confidence="confirmed",
                    stale_after_days=1,
                )
                add_memory(
                    connection,
                    kind="fact",
                    scope="project-alpha",
                    text="The current deployment target is staging",
                    confidence="confirmed",
                    stale_after_days=30,
                )
                connection.execute(
                    "UPDATE memories SET updated_at = ? WHERE id = ?",
                    ("2020-01-01T00:00:00+00:00", stale["id"]),
                )
                connection.commit()
                results = search_memories(
                    connection, query="deployment staging", scope="project-alpha"
                )
                self.assertFalse(results[0]["stale"])
                self.assertTrue(results[1]["stale"])
                self.assertEqual(results[0]["access_count"], 1)
            finally:
                connection.close()

    def test_correction_ledger_tracks_retrieval_and_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                correction = add_correction(
                    connection,
                    scope="global",
                    trigger_text="User says continue after a proposed validation step",
                    correction="Resume validation instead of asking for the background again",
                    severity="high",
                    evidence="User correction in a prior session",
                )
                found = search_corrections(
                    connection, query="continue validation", scope="project-alpha"
                )
                self.assertEqual(found[0]["id"], correction["id"])
                self.assertEqual(found[0]["retrieved_count"], 1)
                updated = record_correction_outcome(
                    connection,
                    correction_id=correction["id"],
                    outcome="recurred",
                    context="Agent asked the user to repeat the task",
                )
                self.assertEqual(updated["recurred_count"], 1)
            finally:
                connection.close()

    def test_intent_check_requires_confirmation_for_external_high_impact_work(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                result = check_intent(
                    connection,
                    scope="project-alpha",
                    goal="Publish the repository and send the profile",
                    impact="high",
                    reversible="no",
                    external=True,
                    sensitive=True,
                    authorization="unknown",
                )
                self.assertTrue(result["confirmation_required"])
                self.assertFalse(result["blocked"])
                self.assertGreaterEqual(len(result["reasons"]), 3)

                denied = check_intent(
                    connection,
                    scope="project-alpha",
                    goal="Publish the repository",
                    impact="high",
                    reversible="no",
                    external=True,
                    authorization="denied",
                )
                self.assertTrue(denied["blocked"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
