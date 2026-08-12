#!/usr/bin/env python3
"""Evaluate compose_skills.py against JSONL regression cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from compose_skills import plan_composition
from discover_skills import default_roots, discover_skills


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
    return records


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=1.0)
    args = parser.parse_args()

    cases = read_jsonl(args.cases)
    discovered_registry = discover_skills(default_roots())
    failures = []
    checks = 0
    matched = 0
    for case in cases:
        if case.get("available_skills"):
            registry = {
                "skills": [
                    {"name": name, "description": name, "path": f"/skills/{name}"}
                    for name in case["available_skills"]
                ]
            }
        else:
            registry = discovered_registry
        result = plan_composition(case["utterance"], case.get("context", ""), registry)
        expected = case["expected"]
        for field in ("primary_skill", "pre_skills", "post_skills"):
            checks += 1
            if result[field] == expected[field]:
                matched += 1
            else:
                failures.append({"id": case["id"], "field": field, "expected": expected[field], "actual": result[field]})
        checks += 1
        if result["composition_size"] <= expected.get("max_eager_skills", 4):
            matched += 1
        else:
            failures.append({"id": case["id"], "field": "composition_size", "actual": result["composition_size"]})

    accuracy = matched / checks if checks else 0.0
    payload = {"cases": len(cases), "checks": checks, "matched": matched, "accuracy": accuracy, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if accuracy >= args.threshold else 2


if __name__ == "__main__":
    raise SystemExit(main())
