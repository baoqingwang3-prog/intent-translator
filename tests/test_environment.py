import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from detect_environment import inspect_environment  # noqa: E402


class EnvironmentTests(unittest.TestCase):
    def test_supported_platform_uses_portable_sqlite_default(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = inspect_environment(
                home=base / "home",
                cwd=base / "project",
                env={},
                which=lambda _: None,
                system="Linux",
                python_version=(3, 10, 0),
            )
            self.assertTrue(report["compatible"])
            self.assertEqual(report["memory"]["recommended_adapter"], "sqlite")
            self.assertEqual(report["hosts"], [])

    def test_detects_multiple_hosts_and_optional_obsidian(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            (home / ".codex").mkdir(parents=True)
            (home / ".claude").mkdir(parents=True)
            (home / ".cursor").mkdir(parents=True)
            (home / ".gemini").mkdir(parents=True)
            report = inspect_environment(
                home=home,
                cwd=base,
                env={"OBSIDIAN_VAULT": str(base / "vault")},
                which=lambda _: None,
                system="Windows",
                python_version=(3, 12, 1),
            )
            self.assertEqual(report["hosts"], ["codex", "claude-code", "cursor", "gemini-cli"])
            self.assertTrue(report["memory"]["obsidian_available"])
            self.assertEqual(report["memory"]["recommended_adapter"], "sqlite")

    def test_old_python_is_incompatible(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = inspect_environment(
                home=base,
                cwd=base,
                env={},
                which=lambda _: None,
                system="Darwin",
                python_version=(3, 9, 9),
            )
            self.assertFalse(report["compatible"])
            self.assertFalse(report["python"]["supported"])
            self.assertTrue(any("Python 3.10" in warning for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
