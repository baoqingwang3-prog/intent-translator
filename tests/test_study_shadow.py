import tempfile
import unittest
from pathlib import Path

from intent_translator_mcp.study_shadow import (
    connect,
    list_pointers,
    observe_shadow,
    render_pointer_index,
    review_shadow,
    sync_pointer_index,
    upsert_pointer,
)


class StudyShadowTests(unittest.TestCase):
    def profile(self, temp: str, *, enabled: bool = True, preview_chars: int = 0):
        return {
            "profile_id": "test-profile",
            "memory": {"location": str(Path(temp) / "memory.db")},
            "shadow_evaluation": {
                "enabled": enabled,
                "retention_days": 30,
                "max_events": 2,
                "store_full_utterance": False,
                "preview_chars": preview_chars,
            },
            "knowledge_pointers": {
                "vault_path": temp,
                "vault_name": "",
                "managed_note": "AI/intent-translator-study-index.md",
            },
        }

    def test_shadow_is_opt_in_and_zero_preview_stores_no_utterance(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "memory.db")
            disabled = observe_shadow(
                connection,
                self.profile(temp, enabled=False),
                utterance="继续复习语言认证阅读",
                compiler_mode="change",
                host_mode="answer",
            )
            self.assertFalse(disabled["recorded"])
            result = observe_shadow(
                connection,
                self.profile(temp),
                utterance="继续复习语言认证阅读并使用 C:\\private\\notes.md",
                compiler_mode="change",
                compiler_skill="study-assistant",
                host_mode="answer",
                host_clarification=True,
                subject="english",
                exam_goal="语言认证",
                context_switched=True,
            )
            row = connection.execute("SELECT * FROM shadow_events").fetchone()
            self.assertTrue(result["recorded"])
            self.assertEqual(row["utterance_preview"], "")
            self.assertNotIn("继续复习语言认证阅读", row["utterance_hash"])
            report = review_shadow(connection)
            self.assertEqual(report["counts"]["intent_mismatches"], 1)
            self.assertEqual(report["counts"]["unnecessary_clarifications"], 1)
            connection.close()

    def test_retention_caps_event_count(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self.profile(temp)
            connection = connect(Path(temp) / "memory.db")
            for index in range(3):
                observe_shadow(connection, profile, utterance=f"case {index}", compiler_mode="answer", host_mode="answer")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM shadow_events").fetchone()[0], 2)
            connection.close()

    def test_pointer_index_syncs_without_scanning_vault(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self.profile(temp)
            connection = connect(Path(temp) / "memory.db")
            upsert_pointer(
                connection,
                path="语言认证/阅读错题.md",
                title="语言认证阅读错题",
                purpose="复盘定位题",
                subject="english",
                exam_goal="语言认证",
                authority_level="personal",
            )
            pointers = list_pointers(connection, exam_goal="语言认证")
            content = render_pointer_index(pointers)
            result = sync_pointer_index(profile, content)
            note = Path(temp) / "AI" / "intent-translator-study-index.md"
            self.assertTrue(result["synced"])
            self.assertTrue(note.exists())
            self.assertIn("语言认证阅读错题", note.read_text(encoding="utf-8"))
            connection.close()

    def test_sync_rejects_managed_note_outside_vault(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self.profile(temp)
            profile["knowledge_pointers"]["managed_note"] = "../outside.md"
            with self.assertRaises(ValueError):
                sync_pointer_index(profile, "content")


if __name__ == "__main__":
    unittest.main()
