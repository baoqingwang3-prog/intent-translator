import sys
import tempfile
import unittest
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from memory_store import (  # noqa: E402
    add_correction,
    add_memory,
    confirm_pending_correction,
    check_intent,
    connect,
    export_store,
    list_memories,
    record_correction_outcome,
    search_corrections,
    search_memories,
    set_memory_status,
    suggest_correction,
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

    def test_read_only_search_does_not_change_access_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                record = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="Prefer concise answers",
                    confidence="confirmed",
                )
                result = search_memories(
                    connection,
                    query="concise answers",
                    track_access=False,
                )[0]
                self.assertEqual(result["access_count"], 0)
                stored = connection.execute(
                    "SELECT access_count FROM memories WHERE id = ?", (record["id"],)
                ).fetchone()
                self.assertEqual(stored["access_count"], 0)
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

    def test_conflicts_are_flagged_and_replace_supersedes_old_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                first = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="回答保持详细",
                    confidence="confirmed",
                    conflict_key="response-detail",
                )
                flagged = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="回答尽量简洁",
                    confidence="confirmed",
                    conflict_key="response-detail",
                )
                self.assertEqual(flagged["conflict_ids"], [first["id"]])
                self.assertTrue(flagged["requires_clarification"])

                replacement = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="先给结论，再给必要细节",
                    confidence="confirmed",
                    conflict_key="response-detail",
                    conflict_resolution="replace",
                )
                active = list_memories(connection)
                self.assertEqual([item["id"] for item in active], [replacement["id"]])
                inactive = list_memories(connection, include_inactive=True)
                statuses = {item["id"]: item["status"] for item in inactive}
                self.assertEqual(statuses[first["id"]], "superseded")
                self.assertEqual(statuses[flagged["id"]], "superseded")
            finally:
                connection.close()

    def test_project_scope_outranks_global_and_marks_shadowing(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                global_memory = add_memory(
                    connection,
                    kind="decision",
                    scope="global",
                    text="默认使用 Markdown 保存笔记",
                    confidence="confirmed",
                    conflict_key="notes-backend",
                )
                project_memory = add_memory(
                    connection,
                    kind="decision",
                    scope="project-alpha",
                    text="这个项目使用 Obsidian 保存笔记",
                    confidence="confirmed",
                    conflict_key="notes-backend",
                )
                results = search_memories(
                    connection, query="保存笔记", scope="project-alpha", track_access=False
                )
                self.assertEqual(results[0]["id"], project_memory["id"])
                global_result = next(item for item in results if item["id"] == global_memory["id"])
                self.assertEqual(
                    global_result["governance"]["shadowed_by_ids"], [project_memory["id"]]
                )
                self.assertFalse(results[0]["governance"]["requires_clarification"])
            finally:
                connection.close()

    def test_sensitive_memory_requires_retention_and_retraction_hides_it(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                with self.assertRaises(ValueError):
                    add_memory(
                        connection,
                        kind="health",
                        scope="global",
                        text="对青霉素过敏",
                        confidence="confirmed",
                        sensitivity="sensitive",
                    )
                memory = add_memory(
                    connection,
                    kind="health",
                    scope="global",
                    text="对青霉素过敏",
                    confidence="confirmed",
                    sensitivity="sensitive",
                    retain_days=30,
                )
                self.assertTrue(memory["expires_at"])
                set_memory_status(
                    connection, memory_id=memory["id"], status="retracted", reason="user withdrew it"
                )
                self.assertEqual(search_memories(connection, query="青霉素过敏"), [])
            finally:
                connection.close()

    def test_chinese_ngram_search_recalls_unsegmented_near_expression(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                memory = add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="回答要简洁直接，先说结果",
                    confidence="confirmed",
                )
                results = search_memories(
                    connection, query="简洁点直接说结果", scope="global", track_access=False
                )
                self.assertEqual(results[0]["id"], memory["id"])
            finally:
                connection.close()

    def test_low_friction_correction_requires_confirmation_before_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                pending = suggest_correction(
                    connection,
                    message="太复杂了",
                    previous_behavior="Used a long architecture explanation for a simple confirmation",
                )
                self.assertTrue(pending["ready_for_confirmation"])
                self.assertEqual(search_corrections(connection, query="architecture"), [])
                confirmed = confirm_pending_correction(connection, pending["id"])
                self.assertEqual(confirmed["status"], "confirmed")
                found = search_corrections(connection, query="architecture explanation")
                self.assertEqual(found[0]["id"], confirmed["correction"]["id"])
            finally:
                connection.close()

    def test_export_contains_governance_history(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            try:
                add_memory(
                    connection,
                    kind="preference",
                    scope="global",
                    text="Prefer concise answers",
                    confidence="confirmed",
                )
                exported = export_store(connection)
                self.assertEqual(exported["schema_version"], 3)
                self.assertEqual(len(exported["tables"]["memories"]), 1)
                self.assertGreaterEqual(len(exported["tables"]["memory_events"]), 1)
            finally:
                connection.close()

    def test_existing_database_is_backed_up_before_schema_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "memory.db"
            legacy = sqlite3.connect(db_path)
            legacy.execute(
                "CREATE TABLE memories (id INTEGER PRIMARY KEY, kind TEXT, scope TEXT, text TEXT, confidence TEXT, source TEXT, created_at TEXT, updated_at TEXT, UNIQUE(kind, scope, text))"
            )
            legacy.commit()
            legacy.close()

            connection = connect(db_path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            finally:
                connection.close()
            backups = list(Path(temp).glob("memory.db.bak-v0-*") )
            self.assertEqual(len(backups), 1)
            self.assertGreater(backups[0].stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
