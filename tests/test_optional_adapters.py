import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from plugin_manager import (  # noqa: E402
    discover_plugins,
    invoke_plugin,
    plugin_status,
    set_plugin_enabled,
)


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
                    corrections=["Do not treat discussion as publication authorization"],
                )
                loaded = session_hooks.load_snapshot(connection, project="alpha")
                self.assertEqual(loaded["next_action"], "Run evaluation")
                self.assertEqual(loaded["decisions"], ["SQLite remains the default"])
                self.assertEqual(len(loaded["corrections"]), 1)
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
                restored = context_pack.retrieve(connection, manifest[0]["marker"])
                self.assertEqual(restored["content"], "Keep exact authorization boundaries.")
                self.assertLessEqual(len(manifest[0]["preview"]), 10)
                self.assertTrue(restored["integrity_verified"])
                self.assertIn(digest, manifest[0]["compact_text"])
            finally:
                connection.close()

    def test_plugins_are_disabled_by_default_and_require_enablement(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            status = {item["name"]: item for item in plugin_status(profile)}
            self.assertEqual(set(status), {"memory-breathing", "reversible-context"})
            self.assertFalse(status["memory-breathing"]["enabled"])
            with self.assertRaisesRegex(ValueError, "plugin is disabled"):
                invoke_plugin(
                    profile,
                    "memory-breathing",
                    "session_start",
                    {"project": "alpha"},
                    state_path=Path(temp) / "memory-breathing.db",
                )

    def test_memory_breathing_loads_bounded_relevant_handoffs(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            state = Path(temp) / "memory-breathing.db"
            set_plugin_enabled(profile, "memory-breathing", True)
            invoke_plugin(
                profile,
                "memory-breathing",
                "session_end",
                {
                    "project": "alpha",
                    "summary": "Finished the installer documentation.",
                    "next_action": "Review screenshots",
                },
                state_path=state,
            )
            invoke_plugin(
                profile,
                "memory-breathing",
                "session_end",
                {
                    "project": "alpha",
                    "summary": "Hardened authorization boundaries.",
                    "next_action": "Run the privacy gate",
                    "decisions": ["Publication still requires explicit confirmation"],
                    "corrections": ["A short approval cannot authorize unrelated actions"],
                },
                state_path=state,
            )
            result = invoke_plugin(
                profile,
                "memory-breathing",
                "session_start",
                {"project": "alpha", "query": "authorization confirmation", "limit": 1},
                state_path=state,
            )["result"]
            self.assertEqual(result["loaded_count"], 1)
            self.assertIn("authorization", result["snapshots"][0]["summary"].casefold())
            self.assertLessEqual(result["loaded_count"], result["max_loaded"])

    def test_reversible_context_plugin_preserves_pointer_hash_and_content(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            state = Path(temp) / "reversible-context.db"
            set_plugin_enabled(profile, "reversible-context", True)
            packed = invoke_plugin(
                profile,
                "reversible-context",
                "pack",
                {
                    "sections": [
                        {
                            "id": "authorization",
                            "content": "Never expand publication authorization from a conceptual approval.",
                            "summary": "Keep publication confirmation explicit.",
                            "source_pointer": "conversation:turn-42",
                        }
                    ]
                },
                state_path=state,
            )["result"]["sections"][0]
            restored = invoke_plugin(
                profile,
                "reversible-context",
                "get",
                {"marker": packed["marker"]},
                state_path=state,
            )["result"]
            self.assertEqual(restored["source_pointer"], "conversation:turn-42")
            self.assertTrue(restored["integrity_verified"])
            self.assertEqual(
                restored["content"],
                "Never expand publication authorization from a conceptual approval.",
            )

    def test_reversible_context_keeps_multiple_source_pointers_for_identical_content(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = context_pack.connect(Path(temp) / "context.db")
            try:
                content = "One exact source section."
                first = context_pack.pack_sections(
                    connection,
                    context_pack.normalize_sections(
                        {"sections": [{"content": content, "source_pointer": "file:a.md"}]}
                    ),
                )[0]
                context_pack.pack_sections(
                    connection,
                    context_pack.normalize_sections(
                        {"sections": [{"content": content, "source_pointer": "file:b.md"}]}
                    ),
                )
                restored = context_pack.retrieve(connection, first["marker"])
                self.assertEqual(restored["source_pointers"], ["file:a.md", "file:b.md"])
            finally:
                connection.close()

    def test_reversible_context_rejects_corrupted_stored_content(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = context_pack.connect(Path(temp) / "context.db")
            try:
                item = context_pack.pack_sections(
                    connection,
                    context_pack.normalize_sections({"sections": [{"content": "original"}]}),
                )[0]
                connection.execute(
                    "UPDATE context_blobs SET content = 'changed' WHERE content_hash = ?",
                    (item["content_hash"],),
                )
                connection.commit()
                with self.assertRaisesRegex(ValueError, "integrity verification"):
                    context_pack.retrieve(connection, item["marker"])
            finally:
                connection.close()

    def test_plugin_manifest_rejects_entrypoint_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin = root / "bad-plugin"
            plugin.mkdir()
            (root / "outside.py").write_text("PLUGIN_API_VERSION = 1\n", encoding="utf-8")
            (plugin / "adapter.json").write_text(
                """{
  "schema_version": 1,
  "name": "bad-plugin",
  "profile_key": "bad_plugin",
  "entrypoint": "../outside.py",
  "default_state": "~/.intent-translator/plugins/bad.db",
  "default_enabled": false,
  "operations": ["run"],
  "network": false
}\n""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "escapes the plugin directory"):
                discover_plugins(root)


if __name__ == "__main__":
    unittest.main()
