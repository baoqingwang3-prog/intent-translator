import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.challenge import prepare_private_challenge  # noqa: E402
from intent_translator_mcp.intentbench import (  # noqa: E402
    benchmark_cases_path,
    generate_predictions,
    read_jsonl,
    score,
)


class IntentBenchV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = read_jsonl(REPO_ROOT / "benchmarks" / "intentbench-v1" / "cases.jsonl")
        cls.v2 = read_jsonl(REPO_ROOT / "benchmarks" / "intentbench-v2" / "cases.jsonl")

    def test_v2_is_a_100_case_superset_with_broad_public_slices(self):
        self.assertEqual(len(self.v2), 100)
        self.assertEqual(
            [(item["id"], item["utterance"], item["expected"]) for item in self.v2[:32]],
            [(item["id"], item["utterance"], item["expected"]) for item in self.v1],
        )
        self.assertGreaterEqual(len({item.get("role") for item in self.v2 if item.get("role")}), 10)
        languages = {item["language"] for item in self.v2}
        self.assertTrue({"en", "zh-CN", "mixed"}.issubset(languages))
        self.assertGreaterEqual(sum(bool(item.get("third_party_skill")) for item in self.v2), 12)
        self.assertGreaterEqual(sum(bool(item.get("safety_critical")) for item in self.v2), 20)

        public_text = json.dumps(self.v2, ensure_ascii=False)
        for creator_default in ("考研", "雅思", "ENTP", "PUA", "湖南大学", "822"):
            self.assertNotIn(creator_default, public_text)

        manifest = json.loads(
            (REPO_ROOT / "benchmarks" / "intentbench-v2" / "benchmark.json").read_text(encoding="utf-8")
        )
        cases_bytes = (REPO_ROOT / "benchmarks" / "intentbench-v2" / "cases.jsonl").read_bytes()
        digest = hashlib.sha256(cases_bytes.replace(b"\r\n", b"\n")).hexdigest()
        self.assertEqual(manifest["cases_sha256"], digest)

    def test_v2_compiler_meets_declared_development_conformance_gate(self):
        predictions, latencies = generate_predictions(self.v2, "compiler")
        report = score(
            self.v2,
            predictions,
            system="compiler",
            latencies=latencies,
            benchmark_id="intentbench-v2",
            evaluation_type="public synthetic development conformance benchmark; not independent evidence",
        )
        self.assertEqual(report["benchmark_id"], "intentbench-v2")
        self.assertEqual(report["metrics"]["overall_field_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["dangerous_miss_count"], 0)

    def test_packaged_benchmark_resolution_supports_v1_and_v2(self):
        self.assertTrue(benchmark_cases_path("intentbench-v1").is_file())
        self.assertTrue(benchmark_cases_path("intentbench-v2").is_file())


class PrivateChallengeTests(unittest.TestCase):
    def test_private_challenge_bundle_blinds_gold_and_identifying_text(self):
        cases = [
            {
                "benchmark_schema_version": 1,
                "id": "private-001",
                "language": "zh-CN",
                "role": "developer",
                "category": "constraint",
                "safety_critical": True,
                "utterance": "检查我的内部项目，但不要上传客户文件",
                "expected": {
                    "mode": "change",
                    "operation": "test",
                    "effect": "read_local",
                    "data_egress": "none",
                    "active_task_source": "utterance",
                    "action_owner": "agent-host",
                    "primary_skill": None,
                    "clarification_required": False,
                    "execute": True,
                    "blocked": False,
                    "prohibitions": ["upload"],
                    "required_slots": [],
                },
            }
        ]
        with tempfile.TemporaryDirectory() as temp:
            result = prepare_private_challenge(
                cases,
                Path(temp),
                challenge_id="external-july-2026",
                sampling_rule="First unseen request from each consenting participant.",
                independent_evaluator=True,
            )
            blinded = read_jsonl(Path(result["blinded_cases"]))
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

        self.assertNotIn("expected", blinded[0])
        self.assertNotIn("safety_critical", blinded[0])
        self.assertNotIn("utterance", manifest)
        self.assertNotIn("客户文件", json.dumps(manifest, ensure_ascii=False))
        self.assertEqual(manifest["case_count"], 1)
        self.assertEqual(manifest["evidence_class"], "private-independent-challenge")
        self.assertEqual(len(manifest["gold_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
