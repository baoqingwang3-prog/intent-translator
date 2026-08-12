import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_TESTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"


class SkillScriptRegressionTests(unittest.TestCase):
    def test_learning_lifecycle_regressions_are_in_release_gate(self):
        subprocess.run(
            [sys.executable, str(SCRIPT_TESTS / "test_learning_lifecycle.py")],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_skill_registry_regressions_are_in_release_gate(self):
        subprocess.run(
            [sys.executable, str(SCRIPT_TESTS / "test_skill_registry.py")],
            check=True,
            cwd=REPO_ROOT,
        )


if __name__ == "__main__":
    unittest.main()
