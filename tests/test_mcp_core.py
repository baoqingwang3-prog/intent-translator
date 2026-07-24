import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.ab_eval import read_jsonl, run  # noqa: E402
from intent_translator_mcp.config import HOSTS, generate_config  # noqa: E402
from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": name, "description": name}
        for name in (
            "obsidian-cli",
            "skill-creator",
            "domain-modeling",
            "diagnosing-bugs",
            "agent-reach",
            "pdf",
            "scientific-critical-thinking",
            "prompt-lookup",
        )
    ],
    "errors": [],
}


class McpCoreTests(unittest.TestCase):
    def test_compiles_short_approval_with_context(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            compiler = IntentCompiler(registry=REGISTRY)
            result = compiler.compile(
                CompileRequest(
                    utterance="可以",
                    context="The agent proposed creating and validating a Skill.",
                )
            )
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["routing"]["primary_skill"], "skill-creator")
            self.assertFalse(result["clarification_required"])
            self.assertEqual(result["decision_receipt"]["mode"], "build")

    def test_external_publication_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            result = IntentCompiler(registry=REGISTRY).compile(
                CompileRequest(utterance="把这个发到 GitHub 上")
            )
            self.assertEqual(result["path"], "review")
            self.assertTrue(result["clarification_required"])
            self.assertTrue(result["risk"]["external"])

    def test_generates_every_host_config(self):
        for host in HOSTS:
            payload = generate_config(host, "/tmp/intent-translator-mcp", "/tmp/skill")
            self.assertIn("intent-translator", payload)
            self.assertIn("/tmp/intent-translator-mcp", payload)
            self.assertIn("PYTHONUTF8", payload)
            self.assertIn("PYTHONIOENCODING", payload)

    def test_ab_eval_improves_over_baseline(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
            },
        ):
            cases = read_jsonl(REPO_ROOT / "evals" / "cases.jsonl")
            with patch("intent_translator_mcp.ab_eval.IntentCompiler", lambda: IntentCompiler(registry=REGISTRY)):
                result = run(cases)
            self.assertGreater(result["compiler"]["overall_accuracy"], result["baseline"]["overall_accuracy"])
            self.assertLess(result["compiler"]["wrong_authorization_count"], result["baseline"]["wrong_authorization_count"])


if __name__ == "__main__":
    unittest.main()
