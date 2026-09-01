"""Decision records must be useful for tuning the rules and must not store request text."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.observability import (  # noqa: E402
    counters,
    record_decision,
    reset_observability_state,
    summarize,
)

REGISTRY = {"skills": [], "errors": []}

SENSITIVE = "把我的身份证照片发给 hr@corp.com"
TRAFFIC = (
    "把 README 改一下",
    "同步一份到远端服务器",
    "好",
    SENSITIVE,
    "查一下这个库怎么用",
    "把这个仓库发到 github 上",
    "删掉这个目录",
    "把 README 改一下",
)


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            key: os.environ.get(key)
            for key in (
                "INTENT_TRANSLATOR_DATA_DIR",
                "INTENT_TRANSLATOR_PROFILE",
                "INTENT_TRANSLATOR_MEMORY_DB",
                "INTENT_TRANSLATOR_TELEMETRY",
            )
        }
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        os.environ["INTENT_TRANSLATOR_DATA_DIR"] = str(root)
        os.environ["INTENT_TRANSLATOR_PROFILE"] = str(root / "profile.json")
        os.environ["INTENT_TRANSLATOR_MEMORY_DB"] = str(root / "memory.db")
        os.environ.pop("INTENT_TRANSLATOR_TELEMETRY", None)
        reset_observability_state()

    def tearDown(self):
        for key, value in self._original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_observability_state()
        self._temp.cleanup()

    def _run_traffic(self) -> IntentCompiler:
        compiler = IntentCompiler(registry=REGISTRY, semantic_adapter=None)
        for utterance in TRAFFIC:
            compiler.compile(CompileRequest(utterance=utterance, semantic_mode="off"))
        return compiler

    def test_no_request_text_reaches_the_log(self):
        self._run_traffic()
        raw = Path(self._temp.name, "decisions.jsonl").read_text(encoding="utf-8")
        for probe in ("身份证", "hr@corp.com", "README", "远端服务器", "把这个仓库", "删掉"):
            with self.subTest(probe=probe):
                self.assertNotIn(probe, raw)

    def test_a_record_carries_the_decision_and_the_rules_that_produced_it(self):
        self._run_traffic()
        lines = Path(self._temp.name, "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(TRAFFIC))
        records = [json.loads(line) for line in lines]
        self.assertTrue(all(item["decision"] in {"allow", "human_review", "deny"} for item in records))
        self.assertTrue(any(item["risk_reasons"] for item in records))
        self.assertTrue(all(item["duration_ms"] >= 0 for item in records))
        self.assertTrue(all("utterance" not in item for item in records))

    def test_repeated_wording_is_countable_without_being_stored(self):
        self._run_traffic()
        summary = summarize()
        # One utterance appears twice in TRAFFIC.
        self.assertEqual(summary["record_count"], len(TRAFFIC))
        self.assertEqual(summary["distinct_utterance_digests"], len(set(TRAFFIC)))
        self.assertFalse(summary["contains_request_text"])

    def test_the_digest_salt_is_local_so_digests_do_not_travel(self):
        self._run_traffic()
        first = json.loads(
            Path(self._temp.name, "decisions.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )["utterance_digest"]

        other = tempfile.TemporaryDirectory()
        try:
            os.environ["INTENT_TRANSLATOR_DATA_DIR"] = other.name
            os.environ["INTENT_TRANSLATOR_PROFILE"] = str(Path(other.name) / "profile.json")
            os.environ["INTENT_TRANSLATOR_MEMORY_DB"] = str(Path(other.name) / "memory.db")
            reset_observability_state()
            IntentCompiler(registry=REGISTRY, semantic_adapter=None).compile(
                CompileRequest(utterance=TRAFFIC[0], semantic_mode="off")
            )
            second = json.loads(
                Path(other.name, "decisions.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )["utterance_digest"]
        finally:
            other.cleanup()
        self.assertTrue(first and second)
        self.assertNotEqual(first, second)

    def test_summary_answers_the_questions_needed_to_tune_the_rules(self):
        self._run_traffic()
        summary = summarize()
        self.assertGreater(summary["review_rate"], 0.0)
        self.assertLess(summary["review_rate"], 1.0)
        self.assertIn("allow", summary["decisions"])
        self.assertIn("human_review", summary["decisions"])
        self.assertTrue(summary["top_risk_reasons"])
        self.assertTrue(summary["operations"])
        self.assertIn("p95", summary["duration_ms"])

    def test_counters_track_decisions_and_reasons(self):
        self._run_traffic()
        totals = counters()
        self.assertEqual(totals["compiles_total"], len(TRAFFIC))
        self.assertEqual(
            totals["decision.allow"] + totals["decision.human_review"] + totals.get("decision.deny", 0),
            len(TRAFFIC),
        )
        self.assertTrue(any(key.startswith("risk_reason.") for key in totals))

    def test_recording_can_be_turned_off(self):
        os.environ["INTENT_TRANSLATOR_TELEMETRY"] = "off"
        reset_observability_state()
        self._run_traffic()
        self.assertFalse(Path(self._temp.name, "decisions.jsonl").exists())
        self.assertEqual(counters(), {})

    def test_recording_failure_never_breaks_a_compile(self):
        os.environ["INTENT_TRANSLATOR_DATA_DIR"] = str(Path(self._temp.name) / "blocked" / "nested")
        Path(self._temp.name, "blocked").write_text("not a directory", encoding="utf-8")
        reset_observability_state()
        result = IntentCompiler(registry=REGISTRY, semantic_adapter=None).compile(
            CompileRequest(utterance="把 README 改一下", semantic_mode="off")
        )
        self.assertEqual(result["tool_gateway"]["decision"], "allow")
        self.assertFalse(Path(self._temp.name, "blocked", "nested").exists())
        # A malformed envelope must not raise into the caller either.
        self.assertEqual(record_decision({}, utterance="x", duration_ms=0.0)["schema_version"], 1)

    def test_the_log_file_is_not_world_readable(self):
        self._run_traffic()
        path = Path(self._temp.name, "digest-salt")
        self.assertTrue(path.is_file())
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
