import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "intent-translator" / "scripts" / "init_profile.py"
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.atomic_io import atomic_write_json  # noqa: E402


class AtomicProfileTests(unittest.TestCase):
    def test_concurrent_profile_updates_do_not_lose_confirmed_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            subprocess.run(
                [sys.executable, str(SCRIPT), "init", "--profile", str(profile)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "set-phrase",
                        "--profile",
                        str(profile),
                        "--phrase",
                        f"phrase-{index}",
                        "--meaning",
                        f"meaning-{index}",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                for index in range(8)
            ]
            failures = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                if process.returncode != 0:
                    failures.append(stdout + stderr)
            self.assertEqual(failures, [])
            data = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data["phrase_mappings"]),
                [f"phrase-{index}" for index in range(8)],
            )

    def test_concurrent_correction_observations_increment_without_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO_ROOT / "src")
            code = (
                "from pathlib import Path; "
                "from intent_translator_mcp.onboarding import observe_language_correction; "
                f"observe_language_correction(Path({str(profile)!r}), phrase='same phrase', corrected_meaning='same meaning')"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", code],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                for _ in range(8)
            ]
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            observations = json.loads(
                (profile.parent / "language-observations.json").read_text(encoding="utf-8")
            )
            item = next(iter(observations["observations"].values()))
            self.assertEqual(item["count"], 8)

    def test_failed_replace_keeps_previous_document_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            path.write_text('{"stable": true}\n', encoding="utf-8")
            with patch("intent_translator_mcp.atomic_io.os.replace", side_effect=OSError("simulated crash")):
                with self.assertRaisesRegex(OSError, "simulated crash"):
                    atomic_write_json(path, {"stable": False})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"stable": True})
            self.assertEqual(list(path.parent.glob(".profile.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
