import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class McpInstallerTests(unittest.TestCase):
    def test_windows_installer_accepts_pep440_prereleases(self):
        script = (REPO_ROOT / "install-mcp.ps1").read_text(encoding="utf-8")
        pattern = re.search(r"\$version -notmatch '([^']+)'", script)
        self.assertIsNotNone(pattern)
        for version in ("0.7.0", "0.7.0a1", "0.7.0b2", "0.7.0rc3", "0.7.0.dev1"):
            self.assertIsNotNone(re.fullmatch(pattern.group(1), version), version)
        self.assertIn("MCP runtime path is too long", script)

    def test_posix_installer_accepts_pep440_prereleases(self):
        script = (REPO_ROOT / "install-mcp.sh").read_text(encoding="utf-8")
        pattern = re.search(r"grep -Eq '([^']+)'", script)
        self.assertIsNotNone(pattern)
        for version in ("0.7.0", "0.7.0a1", "0.7.0b2", "0.7.0rc3", "0.7.0.dev1"):
            self.assertIsNotNone(re.fullmatch(pattern.group(1), version), version)


if __name__ == "__main__":
    unittest.main()
