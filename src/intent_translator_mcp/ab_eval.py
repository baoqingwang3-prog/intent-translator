"""Compare a naive baseline with deterministic intent compilation."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from .core import IntentCompiler
from .models import CompileRequest


FIELDS = ("path", "mode", "memory_action", "clarification", "primary_skill", "preserve_voice")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def naive_prediction(case: dict[str, Any]) -> dict[str, Any]:
    text = case["utterance"].casefold()
    mode = "search" if "搜索" in text or "查一下" in text else "change" if any(word in text for word in ("改", "装", "删除", "旋转")) else "answer"
    return {
        "path": "fast",
        "mode": mode,
        "memory_action": "none",
        "clarification": False,
        "primary_skill": None,
        "preserve_voice": True,
    }


def compiled_prediction(compiler: IntentCompiler, case: dict[str, Any]) -> dict[str, Any]:
    result = compiler.compile(CompileRequest(utterance=case["utterance"], context=case.get("context", ""), include_prompt=True))
    return {
        "path": result["path"],
        "mode": result["mode"],
        "memory_action": result["memory_action"],
        "clarification": result["clarification_required"],
        "primary_skill": result["routing"]["primary_skill"],
        "preserve_voice": result["preserve_voice"],
        "prompt_chars": len(result.get("host_prompt") or ""),
    }


def score(cases: list[dict[str, Any]], predictions: list[dict[str, Any]], latencies: list[float]) -> dict[str, Any]:
    correct = {field: 0 for field in FIELDS}
    totals = {field: 0 for field in FIELDS}
    wrong_authorization = 0
    for case, prediction in zip(cases, predictions):
        expected = case["expected"]
        for field in FIELDS:
            totals[field] += 1
            correct[field] += prediction.get(field) == expected.get(field)
        if expected.get("clarification") and not prediction.get("clarification"):
            wrong_authorization += 1
    matched = sum(correct.values())
    scored = sum(totals.values())
    return {
        "overall_accuracy": matched / scored,
        "field_accuracy": {field: correct[field] / totals[field] for field in FIELDS},
        "wrong_authorization_count": wrong_authorization,
        "estimated_prompt_tokens_mean": round(statistics.mean([item.get("prompt_chars", 0) / 4 for item in predictions]), 1),
        "latency_ms_mean": round(statistics.mean(latencies) * 1000, 3),
        "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] * 1000, 3),
    }


def run(cases: list[dict[str, Any]]) -> dict[str, Any]:
    compiler = IntentCompiler()
    baseline: list[dict[str, Any]] = []
    compiled: list[dict[str, Any]] = []
    baseline_times: list[float] = []
    compiled_times: list[float] = []
    for case in cases:
        started = time.perf_counter()
        baseline.append(naive_prediction(case))
        baseline_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        compiled.append(compiled_prediction(compiler, case))
        compiled_times.append(time.perf_counter() - started)
    base_score = score(cases, baseline, baseline_times)
    compiler_score = score(cases, compiled, compiled_times)
    return {
        "case_count": len(cases),
        "evaluation_type": "deterministic regression; not a live-model comprehension claim",
        "baseline": base_score,
        "compiler": compiler_score,
        "delta": {
            "overall_accuracy": round(compiler_score["overall_accuracy"] - base_score["overall_accuracy"], 4),
            "wrong_authorization_count": compiler_score["wrong_authorization_count"] - base_score["wrong_authorization_count"],
        },
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/cases.jsonl"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(read_jsonl(args.cases))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

