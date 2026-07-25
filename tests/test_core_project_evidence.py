import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.intentbench import (  # noqa: E402
    BENCHMARK_ID,
    generate_predictions,
    read_jsonl,
    score,
    validate_cases,
)


class IntentBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark_dir = REPO_ROOT / "benchmarks" / "intentbench-v1"
        cls.cases = read_jsonl(cls.benchmark_dir / "cases.jsonl")

    def test_manifest_matches_versioned_public_cases(self):
        validate_cases(self.cases)
        manifest = json.loads((self.benchmark_dir / "benchmark.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["benchmark_id"], BENCHMARK_ID)
        self.assertEqual(manifest["case_count"], len(self.cases))
        self.assertEqual(manifest["safety_critical_case_count"], sum(case["safety_critical"] for case in self.cases))
        self.assertGreaterEqual(len({case["language"] for case in self.cases}), 3)
        self.assertTrue(manifest["development_tuning_disclosed"])
        self.assertFalse(manifest["independent_or_real_user_evidence"])

    def test_compiler_meets_public_conformance_gate(self):
        predictions, latencies = generate_predictions(self.cases, "compiler")
        report = score(self.cases, predictions, system="compiler", latencies=latencies)
        self.assertEqual(report["metrics"]["overall_field_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["constraint_preservation_rate"], 1.0)
        self.assertEqual(report["metrics"]["dangerous_miss_count"], 0)
        self.assertEqual(report["failures"], [])

    def test_keyword_baseline_is_labeled_and_materially_weaker(self):
        compiler_predictions, _ = generate_predictions(self.cases, "compiler")
        keyword_predictions, _ = generate_predictions(self.cases, "keyword")
        compiler = score(self.cases, compiler_predictions, system="compiler")
        keyword = score(self.cases, keyword_predictions, system="keyword")
        self.assertLess(keyword["metrics"]["overall_field_accuracy"], compiler["metrics"]["overall_field_accuracy"])
        self.assertGreater(keyword["metrics"]["dangerous_miss_count"], 0)
        self.assertIn("sanity baseline", " ".join(keyword["claim_limits"]))

    def test_missing_external_predictions_are_all_scored_wrong(self):
        report = score(self.cases, [], system="external")
        self.assertEqual(len(report["missing_ids"]), len(self.cases))
        self.assertEqual(report["metrics"]["overall_field_accuracy"], 0.0)
        self.assertEqual(report["metrics"]["complete_case_rate"], 0.0)


class PublicEvidenceDocumentTests(unittest.TestCase):
    def test_contribution_boundary_separates_prior_art_and_evidence_classes(self):
        text = (REPO_ROOT / "docs" / "contribution-boundary.md").read_text(encoding="utf-8")
        self.assertIn("Prior Art We Do Not Claim", text)
        self.assertIn("Independent reproduction", text)
        self.assertIn("repository stars are not effectiveness evidence", text)
        self.assertIn("Guarantees correct understanding", text)

    def test_threat_model_names_host_bypass_and_all_trust_boundaries(self):
        text = (REPO_ROOT / "docs" / "threat-model.md").read_text(encoding="utf-8")
        for threat_id in range(1, 15):
            self.assertIn(f"T{threat_id:02d}", text)
        self.assertIn("A host that bypasses the preflight", text)
        self.assertIn("Memory and model output cannot grant authorization", text)
        self.assertIn("security/advisories/new", (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
