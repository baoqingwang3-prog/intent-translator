import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


session_hooks = load_module(
    "session_lifecycle",
    REPO_ROOT
    / "skills"
    / "intent-translator"
    / "optional"
    / "session-hooks"
    / "session_lifecycle.py",
)
context_pack = load_module(
    "context_pack",
    REPO_ROOT
    / "skills"
    / "intent-translator"
    / "optional"
    / "reversible-context"
    / "context_pack.py",
)


class OptionalAdapterTests(unittest.TestCase):
    def test_session_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = session_hooks.connect(Path(temp) / "sessions.db")
            try:
                session_hooks.save_snapshot(
                    connection,
                    project="alpha",
                    summary="Implemented routing",
                    next_action="Run evaluation",
                    decisions=["SQLite remains the default"],
                )
                loaded = session_hooks.load_snapshot(connection, project="alpha")
                self.assertEqual(loaded["next_action"], "Run evaluation")
                self.assertEqual(loaded["decisions"], ["SQLite remains the default"])
            finally:
                connection.close()

    def test_reversible_context_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = context_pack.connect(Path(temp) / "context.db")
            try:
                sections = context_pack.normalize_sections(
                    {"sections": [{"id": "rules", "content": "Keep exact authorization boundaries."}]}
                )
                manifest = context_pack.pack_sections(connection, sections, preview_chars=10)
                digest = manifest[0]["content_hash"]
                restored = context_pack.retrieve(connection, digest[:16])
                self.assertEqual(restored["content"], "Keep exact authorization boundaries.")
                self.assertLessEqual(len(manifest[0]["preview"]), 10)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
