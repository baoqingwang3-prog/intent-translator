import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.doctor import run_doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def test_missing_profile_is_warning_and_paths_are_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".intent-translator").mkdir()
            report = run_doctor(home=home, env={})
            self.assertEqual(report["status"], "warn")
            serialized = json.dumps(report)
            self.assertNotIn(str(home.resolve()), serialized)

    def test_missing_data_directory_is_creatable_first_run_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / "new-user-data"
            report = run_doctor(
                home=home,
                env={
                    "INTENT_TRANSLATOR_PROFILE": str(data / "profile.json"),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(data / "memory.db"),
                },
            )
            memory = next(item for item in report["checks"] if item["id"] == "memory")
            self.assertEqual(memory["status"], "warn")
            self.assertEqual(report["status"], "warn")
            self.assertFalse(data.exists())

    def test_invalid_profile_fails_without_echoing_content(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / ".intent-translator"
            data.mkdir()
            profile = data / "profile.json"
            profile.write_text("{not-json", encoding="utf-8")
            report = run_doctor(home=home, env={"INTENT_TRANSLATOR_PROFILE": str(profile)})
            self.assertEqual(report["status"], "fail")
            self.assertNotIn("not-json", json.dumps(report))

    def test_versioned_runtime_state_requires_existing_command(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / ".intent-translator"
            runtime = data / "mcp" / "runtimes" / "0.4.0" / "venv" / "Scripts"
            runtime.mkdir(parents=True)
            command = runtime / "intent-translator-mcp.exe"
            command.touch()
            (data / "mcp" / "current.json").write_text(
                json.dumps({"version": "0.4.0", "command": str(command)}),
                encoding="utf-8",
            )

            report = run_doctor(home=home, env={})
            check = next(item for item in report["checks"] if item["id"] == "mcp_runtime")
            self.assertEqual(check["status"], "pass")
            self.assertEqual(check["details"]["version"], "0.4.0")
            self.assertNotIn(str(home.resolve()), json.dumps(report))

    def test_duplicate_skill_locations_are_visible_and_have_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            first = home / ".codex" / "skills" / "intent-translator"
            second = home / ".agents" / "skills" / "intent-translator"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            with patch("intent_translator_mcp.doctor._candidate_skill_dirs", return_value=[first, second]):
                report = run_doctor(home=home, env={})
            check = next(item for item in report["checks"] if item["id"] == "skill")
            self.assertEqual(check["status"], "warn")
            self.assertEqual(
                check["details"]["active_location"],
                str(Path("~") / ".codex" / "skills" / "intent-translator"),
            )
            self.assertEqual(check["details"]["duplicate_count"], 1)


if __name__ == "__main__":
    unittest.main()
