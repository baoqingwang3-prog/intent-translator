import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.host_registration import (  # noqa: E402
    AWAITING_HOST_EXIT,
    HostRegistrationError,
    codex_registration_status,
    repair_codex_registration,
)


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["codex"], returncode, stdout, stderr)


class HostRegistrationTests(unittest.TestCase):
    def _runtime(self, home: Path, version: str = "0.7.0a2") -> Path:
        command = (
            home
            / ".intent-translator"
            / "mcp"
            / "runtimes"
            / version
            / "venv"
            / ("Scripts" if sys.platform == "win32" else "bin")
            / ("intent-translator-mcp.exe" if sys.platform == "win32" else "intent-translator-mcp")
        )
        command.parent.mkdir(parents=True)
        command.touch()
        state = home / ".intent-translator" / "mcp" / "current.json"
        state.write_text(
            json.dumps({"version": version, "command": str(command)}),
            encoding="utf-8",
        )
        return command

    def _registered(self, command: Path, skill_dir: Path) -> str:
        return json.dumps(
            {
                "name": "intent-translator",
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": str(command),
                    "args": [],
                    "env": {
                        "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8",
                        "INTENT_TRANSLATOR_SKILL_DIR": str(skill_dir),
                    },
                },
            }
        )

    def test_windows_prefers_desktop_cli_over_a_path_shim(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            local = home / "local"
            desktop_cli = local / "OpenAI" / "Codex" / "bin" / "build-id" / "codex.exe"
            desktop_cli.parent.mkdir(parents=True)
            desktop_cli.touch()
            with patch(
                "intent_translator_mcp.host_registration.shutil.which",
                return_value="blocked-path-shim.exe",
            ):
                from intent_translator_mcp.host_registration import find_codex_cli

                discovered = find_codex_cli(
                    home=home,
                    env={"LOCALAPPDATA": str(local), "PATH": "ignored"},
                    platform="nt",
                )
        self.assertEqual(discovered, desktop_cli.resolve())

    def test_process_detection_failure_fails_closed(self):
        with (
            patch("intent_translator_mcp.host_registration.os.name", "nt"),
            patch(
                "intent_translator_mcp.host_registration.subprocess.run",
                return_value=completed(1, stderr="access denied"),
            ),
        ):
            from intent_translator_mcp.host_registration import _codex_is_running

            self.assertTrue(_codex_is_running(env={}))

    def test_not_installed_is_distinct_from_not_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            status = codex_registration_status(home=Path(temp), env={})
        self.assertEqual(status["state"], "not-installed")
        self.assertFalse(status["installed"])

    def test_valid_runtime_without_registration_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._runtime(home)
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=False),
                patch("intent_translator_mcp.host_registration._run_codex", return_value=completed(1, stderr="not found")),
            ):
                status = codex_registration_status(home=home, env={})
        self.assertEqual(status["state"], "installed-not-registered")
        self.assertTrue(status["installed"])
        self.assertFalse(status["registered"])

    def test_unusable_codex_cli_degrades_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._runtime(home)
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    side_effect=PermissionError("blocked"),
                ),
            ):
                status = codex_registration_status(home=home, env={})
        self.assertEqual(status["state"], "registration-unknown")
        self.assertIn("could not inspect", status["message"])

    def test_matching_registration_reports_pending_restart_while_host_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=True),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    return_value=completed(stdout=self._registered(command, skill_dir)),
                ),
            ):
                status = codex_registration_status(home=home, env={})
        self.assertEqual(status["state"], "registered-pending-restart")
        self.assertTrue(status["matches_runtime"])

    def test_matching_registration_accepts_canonical_skill_path_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            aliased_skill_dir = skill_dir.parent / ".." / "skills" / "intent-translator"
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=False),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    return_value=completed(stdout=self._registered(command, aliased_skill_dir)),
                ),
            ):
                status = codex_registration_status(home=home, env={})
        self.assertEqual(status["state"], "registered")
        self.assertTrue(status["matches_runtime"])

    def test_active_runtime_state_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=True),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    return_value=completed(stdout=self._registered(command, skill_dir)),
                ),
            ):
                status = codex_registration_status(home=home, env={}, active_runtime=True)
        self.assertEqual(status["state"], "active")

    def test_stale_registration_is_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            old_command = command.parent.parent.parent.parent / "0.6.0" / command.parent.name / command.name
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=False),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    return_value=completed(stdout=self._registered(old_command, skill_dir)),
                ),
            ):
                status = codex_registration_status(home=home, env={})
        self.assertEqual(status["state"], "registered-stale")
        self.assertFalse(status["matches_runtime"])

    def test_repair_refuses_to_mutate_while_codex_is_running(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._runtime(home)
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=True),
                patch("intent_translator_mcp.host_registration._run_codex") as run,
            ):
                result = repair_codex_registration(home=home, env={})
        self.assertEqual(result["exit_code"], AWAITING_HOST_EXIT)
        self.assertEqual(result["state"], "awaiting-host-exit")
        run.assert_not_called()

    def test_repeated_repair_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=False),
                patch(
                    "intent_translator_mcp.host_registration._run_codex",
                    return_value=completed(stdout=self._registered(command, skill_dir)),
                ) as run,
            ):
                first = repair_codex_registration(home=home, env={})
                second = repair_codex_registration(home=home, env={})
        self.assertEqual(first["state"], "registered")
        self.assertFalse(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(run.call_count, 2)

    def test_failed_native_add_restores_previous_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            command = self._runtime(home)
            old_command = command.with_name("old-intent-translator-mcp.exe")
            skill_dir = home / ".codex" / "skills" / "intent-translator"
            responses = [
                completed(stdout=self._registered(old_command, skill_dir)),
                completed(),
                completed(1, stderr="add failed"),
                completed(),
            ]
            with (
                patch("intent_translator_mcp.host_registration.find_codex_cli", return_value=Path("codex")),
                patch("intent_translator_mcp.host_registration._codex_is_running", return_value=False),
                patch("intent_translator_mcp.host_registration._run_codex", side_effect=responses) as run,
            ):
                with self.assertRaises(HostRegistrationError) as captured:
                    repair_codex_registration(home=home, env={})
        self.assertTrue(captured.exception.restored_previous)
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[1].args[-1][:3], ["mcp", "remove", "intent-translator"])
        self.assertIn(str(old_command), run.call_args_list[3].args[-1])


if __name__ == "__main__":
    unittest.main()
