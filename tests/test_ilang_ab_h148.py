"""Exercise proposal variants through the actual subprocess/compiler boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ilang_ab_h148 as probe  # noqa: E402


class IlangAbH148Tests(unittest.TestCase):
    def test_each_variant_reaches_the_compiler_as_a_semantic_proposal(self):
        for primary, alternatives in (
            (None, []),
            ("agent-reach", []),
            (None, ["agent-reach", "smart-search"]),
        ):
            with self.subTest(primary=primary, alternatives=alternatives):
                result = probe.run(primary, alternatives)
                self.assertEqual(result["semantic"]["status"], "applied")
                proposal = result["semantic"]["proposal"]
                self.assertEqual(proposal["primary_skill"], primary)
                self.assertEqual(proposal["alternatives"], alternatives)
                for field, expected in probe.base.items():
                    self.assertEqual(proposal[field], expected)

    def test_proposal_round_trip_uses_utf8_with_legacy_stdio_defaults(self):
        with patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252"}):
            result = probe.run("agent-reach", ["smart-search"])
        self.assertEqual(result["semantic"]["status"], "applied")
        proposal = result["semantic"]["proposal"]
        self.assertEqual(proposal["normalized_goal"], probe.base["normalized_goal"])
        self.assertEqual(proposal["primary_skill"], "agent-reach")
        self.assertEqual(proposal["alternatives"], ["smart-search"])

    def test_interpretation_alternatives_change_the_execute_decision(self):
        clean = probe.run(None, [])
        alternatives = probe.run(None, ["agent-reach", "smart-search"])
        self.assertEqual(clean["mode"], "search")
        self.assertEqual(alternatives["mode"], clean["mode"])
        self.assertEqual(alternatives["intent_contract"]["data_egress"],
                         clean["intent_contract"]["data_egress"])
        self.assertEqual(alternatives["routing"]["primary_skill"],
                         clean["routing"]["primary_skill"])
        self.assertTrue(clean["completion_contract"]["execute"])
        self.assertFalse(alternatives["completion_contract"]["execute"])
        self.assertTrue(alternatives["clarification_required"])

    def test_import_is_quiet_and_cli_reports_variants_and_live_proposal(self):
        with tempfile.TemporaryDirectory(prefix="ilang-ab-cli-") as temporary:
            imported = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); import ilang_ab_h148",
                 str(ROOT / "scripts")],
                cwd=temporary, capture_output=True, text=True, encoding="utf-8",
                timeout=20, check=True,
            )
            self.assertEqual(imported.stdout, "")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "ilang_ab_h148.py")],
                cwd=temporary, capture_output=True, text=True, encoding="utf-8",
                timeout=20, check=True,
            )
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual([line.split()[0] for line in lines[:3]],
                         ["clean", "primary", "alts-only"])
        self.assertTrue(lines[-1].startswith("subprocess proposal: "))
        live = json.loads(lines[-1].split(": ", 1)[1])
        self.assertEqual(live["mode"], "search")
        self.assertIsNone(live["primary_skill"])
        self.assertEqual(live["alternatives"], [])


if __name__ == "__main__":
    unittest.main()
