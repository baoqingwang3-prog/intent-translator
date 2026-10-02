"""Portable development tools preserve frozen inputs and prior results."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = ROOT / "scripts" / "dev_regression_v3.py"


class IlangPortabilityTests(unittest.TestCase):
    def run_audit(self, *arguments):
        return subprocess.run(
            [sys.executable, str(AUDIT_SCRIPT), *map(str, arguments)],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def test_help_does_not_require_a_machine_specific_audit_directory(self):
        result = self.run_audit("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--audit-dir", result.stdout)
        self.assertIn("--semantic-python", result.stdout)
        self.assertIn("--output", result.stdout)

    def test_existing_result_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prior-result.json"
            original = b'{"acceptance": false}\n'
            output.write_bytes(original)
            result = self.run_audit("--audit-dir", directory, "--output", output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("output already exists", result.stderr)
            self.assertEqual(output.read_bytes(), original)

    def test_missing_frozen_resources_fail_before_model_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-result.json"
            result = self.run_audit("--audit-dir", directory, "--output", output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("frozen audit resource is missing", result.stderr)
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "Windows launcher contract")
    def test_launcher_uses_configured_interpreter_and_forwards_arguments(self):
        environment = dict(os.environ, ILANG_SEMANTIC_PYTHON=sys.executable)
        result = subprocess.run(
            ["cmd", "/c", str(ROOT / "scripts" / "start_semantic_server.cmd"), "--help"],
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--port", result.stdout)


if __name__ == "__main__":
    unittest.main()
