#!/usr/bin/env python3
"""Score intent-translator predictions against JSONL evaluation cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FIELDS = (
    "path",
    "mode",
    "memory_action",
    "clarification",
    "primary_skill",
    "preserve_voice",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
        if "id" not in record:
            raise ValueError(f"{path}:{line_number}: missing id")
        records.append(record)
    return records


def write_template(cases: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            record = {"id": case["id"], **{field: None for field in FIELDS}}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def evaluate(cases: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    prediction_map = {record["id"]: record for record in predictions}
    totals = {field: 0 for field in FIELDS}
    correct = {field: 0 for field in FIELDS}
    missing: list[str] = []

    for case in cases:
        case_id = case["id"]
        expected = case.get("expected", {})
        prediction = prediction_map.get(case_id)
        if prediction is None:
            missing.append(case_id)
            continue
        for field in FIELDS:
            if field not in expected:
                continue
            totals[field] += 1
            if prediction.get(field) == expected[field]:
                correct[field] += 1

    field_accuracy = {
        field: (correct[field] / totals[field] if totals[field] else None) for field in FIELDS
    }
    scored = sum(totals.values())
    matched = sum(correct.values())
    return {
        "case_count": len(cases),
        "prediction_count": len(predictions),
        "missing_ids": missing,
        "field_accuracy": field_accuracy,
        "overall_accuracy": matched / scored if scored else 0.0,
        "matched_fields": matched,
        "scored_fields": scored,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--write-template", type=Path)
    parser.add_argument("--threshold", type=float, default=0.0)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    cases = read_jsonl(args.cases)
    if args.write_template:
        write_template(cases, args.write_template)
        print(json.dumps({"template": str(args.write_template), "cases": len(cases)}, ensure_ascii=False))
        return 0
    if not args.predictions:
        raise SystemExit("--predictions is required unless --write-template is used")
    result = evaluate(cases, read_jsonl(args.predictions))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["missing_ids"] or result["overall_accuracy"] < args.threshold:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
