import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from memory_store import connect, table_exists  # noqa: E402


def _write_corrections(db_path: str, worker: int, count: int, queue) -> None:
    sys.path.insert(0, str(SCRIPTS))
    from memory_store import add_correction, connect

    try:
        connection = connect(Path(db_path))
        for index in range(count):
            add_correction(
                connection,
                scope="global",
                trigger_text=f"worker-{worker}-trigger-{index}",
                correction=f"worker-{worker}-correction-{index}",
                severity="medium",
                evidence="multiprocess regression",
            )
        connection.close()
        queue.put(None)
    except Exception as exc:  # pragma: no cover - surfaced in the parent assertion
        queue.put(repr(exc))


class MemoryConcurrencyTests(unittest.TestCase):
    def test_wal_and_busy_timeout_support_multiple_writer_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "memory.db"
            connection = connect(db_path)
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            connection.close()
            self.assertEqual(str(journal_mode).casefold(), "wal")
            self.assertGreaterEqual(int(busy_timeout), 5000)

            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            workers = [
                context.Process(target=_write_corrections, args=(str(db_path), index, 5, queue))
                for index in range(4)
            ]
            for worker in workers:
                worker.start()
            errors = [queue.get(timeout=30) for _ in workers]
            for worker in workers:
                worker.join(timeout=30)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(errors, [None] * len(workers))

            readonly = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            readonly.row_factory = sqlite3.Row
            try:
                self.assertTrue(table_exists(readonly, "corrections"))
                total = readonly.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
            finally:
                readonly.close()
            self.assertEqual(total, 20)


if __name__ == "__main__":
    unittest.main()
