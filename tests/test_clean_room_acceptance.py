import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CleanRoomAcceptanceTests(unittest.TestCase):
    def test_install_first_route_onboard_and_uninstall_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill_root = root / "codex" / "skills"
            profile = root / "data" / "profile.json"
            memory = root / "data" / "memory.db"
            env = dict(os.environ)
            env.update(
                {
                    "CODEX_HOME": str(root / "codex"),
                    "INTENT_TRANSLATOR_PROFILE": str(profile),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(memory),
                    "INTENT_TRANSLATOR_SKILL_ROOTS": str(skill_root),
                    "PYTHONPATH": str(REPO_ROOT / "src"),
                    "PYTHONUTF8": "1",
                }
            )

            if os.name == "nt":
                install = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "install.ps1"),
                    "-Destination",
                    str(skill_root),
                ]
                uninstall = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "uninstall.ps1"),
                    "-Destination",
                    str(skill_root),
                ]
            else:
                install = ["sh", str(REPO_ROOT / "install.sh"), "--destination", str(skill_root)]
                uninstall = ["sh", str(REPO_ROOT / "uninstall.sh"), "--destination", str(skill_root)]

            subprocess.run(install, check=True, capture_output=True, env=env)
            self.assertTrue((skill_root / "intent-translator" / "SKILL.md").is_file())
            clean_profile = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(clean_profile["phrase_mappings"], {})
            self.assertNotIn("study", clean_profile)

            demo = skill_root / "resume-helper"
            demo.mkdir(parents=True)
            (demo / "SKILL.md").write_text(
                "---\n"
                "name: resume-helper\n"
                "description: Tailor resumes for product manager and software engineering job applications.\n"
                "---\n\n"
                "# Resume Helper\n",
                encoding="utf-8",
            )
            compile_code = (
                "import json; "
                "from intent_translator_mcp.core import IntentCompiler; "
                "from intent_translator_mcp.models import CompileRequest; "
                "r=IntentCompiler().compile(CompileRequest("
                "utterance='Create a tailored resume for a product manager role', authorization='granted', semantic_mode='off')); "
                "print(json.dumps({'mode':r['mode'],'skill':r['routing']['primary_skill'],"
                "'execute':r['completion_contract']['execute'],'personalization':r['personalization_status']['mode']}))"
            )
            compiled = subprocess.run(
                [sys.executable, "-c", compile_code],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            result = json.loads(compiled.stdout)
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["skill"], "resume-helper")
            self.assertTrue(result["execute"])
            self.assertEqual(result["personalization"], "generic")

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intent_translator_mcp.onboarding",
                    "--profile",
                    str(profile),
                    "--memory",
                    "local",
                    "--interpretation",
                    "choices",
                    "--tone",
                    "concise",
                    "--json",
                ],
                check=True,
                capture_output=True,
                env=env,
            )
            configured = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(configured["interpretation_preferences"]["material_ambiguity"], "show-choices")

            subprocess.run(uninstall, check=True, capture_output=True, env=env)
            self.assertFalse((skill_root / "intent-translator").exists())
            self.assertTrue(profile.is_file())


if __name__ == "__main__":
    unittest.main()
