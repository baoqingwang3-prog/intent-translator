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

    def test_reports_skill_copy_and_runtime_version_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            first = home / ".codex" / "skills" / "intent-translator"
            second = home / ".agents" / "skills" / "intent-translator"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "VERSION").write_text("0.7.0a1\n", encoding="utf-8")
            (second / "VERSION").write_text("0.6.0\n", encoding="utf-8")

            runtime = home / ".intent-translator" / "mcp" / "runtimes" / "0.6.0" / "venv" / "Scripts"
            runtime.mkdir(parents=True)
            command = runtime / "intent-translator-mcp.exe"
            command.touch()
            state = home / ".intent-translator" / "mcp" / "current.json"
            state.write_text(
                json.dumps({"version": "0.6.0", "command": str(command)}),
                encoding="utf-8",
            )

            with patch("intent_translator_mcp.doctor._candidate_skill_dirs", return_value=[first, second]):
                report = run_doctor(home=home, env={})

            skill = next(item for item in report["checks"] if item["id"] == "skill")
            alignment = next(item for item in report["checks"] if item["id"] == "version_alignment")
            self.assertEqual(skill["details"]["active_version"], "0.7.0a1")
            self.assertTrue(skill["details"]["versions_differ"])
            self.assertEqual([item["version"] for item in skill["details"]["copies"]], ["0.7.0a1", "0.6.0"])
            self.assertEqual(alignment["status"], "warn")
            self.assertTrue(alignment["details"]["restart_host"])
            self.assertEqual(report["runtime_status"]["state"], "stale")
            self.assertEqual(report["runtime_status"]["versions"]["actual_runtime"], "0.7.0a3")
            self.assertEqual(report["runtime_status"]["versions"]["profile_schema"], None)
            self.assertIn(
                "active Skill and installed MCP runtime differ",
                alignment["details"]["reasons"],
            )

    def test_matching_versioned_host_copies_do_not_create_a_false_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            first = home / ".codex" / "skills" / "intent-translator"
            second = home / ".claude" / "skills" / "intent-translator"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "VERSION").write_text("0.7.0a1\n", encoding="utf-8")
            (second / "VERSION").write_text("0.7.0a1\n", encoding="utf-8")
            with patch("intent_translator_mcp.doctor._candidate_skill_dirs", return_value=[first, second]):
                report = run_doctor(home=home, env={})
            skill = next(item for item in report["checks"] if item["id"] == "skill")
            self.assertEqual(skill["status"], "pass")
            self.assertFalse(skill["details"]["versions_differ"])

    def test_installed_runtime_without_codex_registration_is_degraded(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            runtime = home / ".intent-translator" / "mcp" / "runtimes" / "0.7.0a3" / "venv" / "Scripts"
            runtime.mkdir(parents=True)
            command = runtime / "intent-translator-mcp.exe"
            command.touch()
            (home / ".intent-translator" / "mcp" / "current.json").write_text(
                json.dumps({"version": "0.7.0a3", "command": str(command)}),
                encoding="utf-8",
            )
            registration = {
                "host": "codex",
                "state": "installed-not-registered",
                "message": "Runtime is installed but Codex MCP registration is missing",
                "repair_command": "intent-translator-host repair --host codex",
                "installed": True,
                "registered": False,
                "matches_runtime": False,
                "host_running": False,
                "restart_required": False,
            }
            with patch("intent_translator_mcp.doctor.codex_registration_status", return_value=registration):
                report = run_doctor(home=home, env={})
        check = next(item for item in report["checks"] if item["id"] == "codex_registration")
        self.assertEqual(check["details"]["state"], "installed-not-registered")
        self.assertEqual(report["runtime_status"]["state"], "degraded")
        self.assertFalse(report["runtime_status"]["active"])

    def test_matching_registration_exposes_pending_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            registration = {
                "host": "codex",
                "state": "registered-pending-restart",
                "message": "Registration matches disk; restart Codex",
                "repair_command": "intent-translator-host repair --host codex",
                "installed": True,
                "registered": True,
                "matches_runtime": True,
                "host_running": True,
                "restart_required": True,
            }
            with patch("intent_translator_mcp.doctor.codex_registration_status", return_value=registration):
                report = run_doctor(home=Path(temp), env={})
        check = next(item for item in report["checks"] if item["id"] == "codex_registration")
        self.assertEqual(check["status"], "warn")
        self.assertTrue(check["details"]["restart_required"])


if __name__ == "__main__":
    unittest.main()
