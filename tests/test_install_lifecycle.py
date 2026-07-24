import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class InstallLifecycleTests(unittest.TestCase):
    def run_command(self, args: list[str], env: dict[str, str], *, expect_success: bool = True):
        completed = subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if expect_success and completed.returncode != 0:
            self.fail(completed.stdout + completed.stderr)
        if not expect_success and completed.returncode == 0:
            self.fail("command unexpectedly succeeded: " + " ".join(args))
        return completed

    def test_clean_install_reinstall_rollback_and_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            codex_home = home / ".codex"
            data_root = home / ".intent-translator"
            profile = data_root / "profile.json"
            env = dict(os.environ)
            for key in list(env):
                if key.startswith("INTENT_TRANSLATOR_"):
                    env.pop(key)
            env.update(
                {
                    "HOME": str(home),
                    "CODEX_HOME": str(codex_home),
                    "INTENT_TRANSLATOR_PROFILE": str(profile),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(data_root / "memory.db"),
                    "PYTHONUTF8": "1",
                }
            )
            installed = codex_home / "skills" / "intent-translator"
            marker = installed / "rollback-marker"

            if os.name == "nt":
                shell = shutil.which("powershell") or shutil.which("pwsh")
                if not shell:
                    self.skipTest("PowerShell is unavailable")
                install = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / "install.ps1"), "-TargetHost", "Codex"]
                replace = [*install, "-Replace"]
                uninstall = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / "uninstall.ps1"), "-TargetHost", "Codex", "-DataRoot", str(data_root)]
                purge = [*uninstall, "-PurgeData", "-ConfirmPurge", "DELETE-LOCAL-DATA"]
            else:
                install = ["sh", str(REPO_ROOT / "install.sh"), "--host", "codex"]
                replace = [*install, "--replace"]
                uninstall = ["sh", str(REPO_ROOT / "uninstall.sh"), "--host", "codex", "--data-root", str(data_root)]
                purge = [*uninstall, "--purge-data", "--confirm-purge", "DELETE-LOCAL-DATA"]

            self.run_command(install, env)
            self.assertTrue((installed / "SKILL.md").exists())
            self.assertTrue(profile.exists())

            self.run_command(replace, env)
            marker.write_text("present", encoding="utf-8")
            failed_env = {**env, "INTENT_TRANSLATOR_TEST_FAIL_AFTER_BACKUP": "1"}
            self.run_command(replace, failed_env, expect_success=False)
            self.assertTrue(marker.exists())

            self.run_command(uninstall, env)
            self.assertFalse(installed.exists())
            self.assertTrue(profile.exists())

            self.run_command(install, env)
            no_confirm = [item for item in purge if item not in {"DELETE-LOCAL-DATA"}]
            self.run_command(no_confirm, env, expect_success=False)
            self.assertTrue(profile.exists())
            self.run_command(purge, env)
            self.assertFalse(data_root.exists())


if __name__ == "__main__":
    unittest.main()
