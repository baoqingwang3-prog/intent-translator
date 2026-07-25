import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.intentbench import (  # noqa: E402
    generate_predictions,
    read_jsonl,
)
from intent_translator_mcp.same_model_eval import (  # noqa: E402
    PairValidationError,
    evaluate_pair,
    prepare_bundle,
    validate_pair,
)


class SameModelEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = read_jsonl(REPO_ROOT / "benchmarks" / "intentbench-v1" / "cases.jsonl")
        cls.common = {
            "provider": "example-provider",
            "model_id": "example-model",
            "model_revision": "2026-07-26",
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 7,
            "max_output_tokens": 2048,
            "host_name": "example-host",
            "host_version": "1.0",
            "tool_registry_sha256": "a" * 64,
            "skill_version": "0.7.0a3",
            "skill_sha256": "b" * 64,
        }

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_prepare_bundle_blinds_gold_and_uses_one_shared_input(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            result = prepare_bundle(self.cases, output, **self.common)

            blinded = read_jsonl(output / "cases.blinded.jsonl")
            self.assertEqual([item["id"] for item in blinded], [item["id"] for item in self.cases])
            self.assertTrue(all("expected" not in item for item in blinded))
            self.assertTrue(all("safety_critical" not in item for item in blinded))

            without = json.loads((output / "without-skill-run.json").read_text(encoding="utf-8"))
            with_skill = json.loads((output / "with-skill-run.json").read_text(encoding="utf-8"))
            self.assertEqual(without["input"], with_skill["input"])
            self.assertFalse(without["condition"]["skill_loaded"])
            self.assertTrue(with_skill["condition"]["skill_loaded"])
            self.assertTrue(result["valid_pair"])

            validation = validate_pair(
                without,
                with_skill,
                without_manifest_path=output / "without-skill-run.json",
                with_manifest_path=output / "with-skill-run.json",
                cases=self.cases,
            )
            self.assertTrue(validation["valid_pair"])

    def test_pair_rejects_model_or_tool_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            prepare_bundle(self.cases, output, **self.common)
            without_path = output / "without-skill-run.json"
            with_path = output / "with-skill-run.json"
            without = json.loads(without_path.read_text(encoding="utf-8"))
            with_skill = json.loads(with_path.read_text(encoding="utf-8"))

            changed_model = copy.deepcopy(with_skill)
            changed_model["run_config"]["model_id"] = "different-model"
            with self.assertRaises(PairValidationError) as model_error:
                validate_pair(
                    without,
                    changed_model,
                    without_manifest_path=without_path,
                    with_manifest_path=with_path,
                    cases=self.cases,
                )
            self.assertIn("model_id", str(model_error.exception))

            changed_tools = copy.deepcopy(with_skill)
            changed_tools["run_config"]["tool_registry_sha256"] = "c" * 64
            with self.assertRaises(PairValidationError) as tool_error:
                validate_pair(
                    without,
                    changed_tools,
                    without_manifest_path=without_path,
                    with_manifest_path=with_path,
                    cases=self.cases,
                )
            self.assertIn("tool_registry_sha256", str(tool_error.exception))

    def test_pair_rejects_gold_visibility_or_private_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            prepare_bundle(self.cases, output, **self.common)
            without_path = output / "without-skill-run.json"
            with_path = output / "with-skill-run.json"
            without = json.loads(without_path.read_text(encoding="utf-8"))
            with_skill = json.loads(with_path.read_text(encoding="utf-8"))

            with_skill["run_config"]["gold_visible"] = True
            with self.assertRaises(PairValidationError):
                validate_pair(
                    without,
                    with_skill,
                    without_manifest_path=without_path,
                    with_manifest_path=with_path,
                    cases=self.cases,
                )

    def test_pair_rejects_tampered_condition_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            prepare_bundle(self.cases, output, **self.common)
            without_path = output / "without-skill-run.json"
            with_path = output / "with-skill-run.json"
            without = json.loads(without_path.read_text(encoding="utf-8"))
            with_skill = json.loads(with_path.read_text(encoding="utf-8"))
            (output / "without-skill-instructions.md").write_text(
                "Give deliberately weak answers.\n", encoding="utf-8"
            )

            with self.assertRaises(PairValidationError) as error:
                validate_pair(
                    without,
                    with_skill,
                    without_manifest_path=without_path,
                    with_manifest_path=with_path,
                    cases=self.cases,
                )
            self.assertIn("condition instruction", str(error.exception))

            with_skill["run_config"]["gold_visible"] = False
            with_skill["run_config"]["private_profile_loaded"] = True
            with self.assertRaises(PairValidationError):
                validate_pair(
                    without,
                    with_skill,
                    without_manifest_path=without_path,
                    with_manifest_path=with_path,
                    cases=self.cases,
                )

    def test_evaluate_pair_reports_case_level_gain_and_safety_delta(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            prepare_bundle(self.cases, output, **self.common)
            without_predictions, _ = generate_predictions(self.cases, "keyword")
            with_predictions, _ = generate_predictions(self.cases, "compiler")
            self._write_jsonl(output / "without-skill-predictions.jsonl", without_predictions)
            self._write_jsonl(output / "with-skill-predictions.jsonl", with_predictions)

            report = evaluate_pair(
                self.cases,
                output / "without-skill-run.json",
                output / "with-skill-run.json",
            )
            self.assertTrue(report["valid_pair"])
            self.assertGreater(report["delta"]["overall_field_accuracy"], 0)
            self.assertGreater(len(report["case_transitions"]["improved"]), 0)
            self.assertEqual(report["case_transitions"]["regressed"], [])
            self.assertGreater(len(report["safety_transitions"]["dangerous_miss_fixed"]), 0)
            self.assertEqual(report["safety_transitions"]["dangerous_miss_introduced"], [])
            self.assertIn("same-model", " ".join(report["claim_limits"]).casefold())

    def test_public_readme_documents_the_paired_entrypoint_and_limits(self):
        readme = (REPO_ROOT / "benchmarks" / "intentbench-v1" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("intent_translator_mcp.same_model_eval prepare", readme)
        self.assertIn("intent_translator_mcp.same_model_eval score", readme)
        self.assertIn("operator-reported", readme)


if __name__ == "__main__":
    unittest.main()
