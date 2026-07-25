"""Run the versioned IntentBench conformance benchmark."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from .core import IntentCompiler
from .models import CompileRequest


BENCHMARK_ID = "intentbench-v1"
BENCHMARK_IDS = ("intentbench-v1", "intentbench-v2")
BENCHMARK_SCHEMA_VERSION = 1
FIELDS = (
    "mode",
    "operation",
    "effect",
    "data_egress",
    "active_task_source",
    "action_owner",
    "primary_skill",
    "clarification_required",
    "execute",
    "blocked",
    "prohibitions",
    "required_slots",
)
ROUTE_FIELDS = ("operation", "action_owner", "primary_skill")
CONTROL_FIELDS = (
    "effect",
    "data_egress",
    "clarification_required",
    "execute",
    "blocked",
)
LIST_FIELDS = {"prohibitions", "required_slots"}

FROZEN_REGISTRY = {
    "skills": [
        {"name": "agent-reach", "description": "Search and research GitHub and the public internet"},
        {"name": "skill-lookup", "description": "Search installed Skills and public Skill registries"},
        {"name": "skill-installer", "description": "Install selected Agent Skills and dependencies"},
        {"name": "skill-creator", "description": "Create, update, and validate Agent Skills"},
        {"name": "prompt-lookup", "description": "Find and improve prompt templates"},
        {"name": "browser", "description": "Run browser and Playwright tests"},
        {"name": "obsidian-cli", "description": "Read and update explicitly selected Obsidian notes"},
        {"name": "pdf", "description": "Read and edit PDF files"},
        {"name": "docx", "description": "Read and edit Microsoft Word DOCX documents"},
        {"name": "xlsx", "description": "Read and edit Excel XLSX workbooks and spreadsheets"},
        {"name": "diagnosing-bugs", "description": "Diagnose software failures without changing files"},
    ],
    "errors": [],
}
GENERIC_PROFILE = {
    "schema_version": 1,
    "profile_id": "intentbench-generic",
    "language": "auto",
    "phrase_mappings": {},
    "memory": {"adapter": "off"},
    "cognitive_priors": [],
}


def read_jsonl(path: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
        case_id = str(record.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"{path}:{line_number}: missing id")
        if case_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate id {case_id}")
        seen.add(case_id)
        records.append(record)
    return records


def benchmark_cases_path(benchmark_id: str = BENCHMARK_ID) -> Any:
    if benchmark_id not in BENCHMARK_IDS:
        raise ValueError(f"unsupported benchmark: {benchmark_id}")
    repository_path = Path("benchmarks") / benchmark_id / "cases.jsonl"
    if repository_path.exists():
        return repository_path
    return importlib.resources.files("intent_translator_mcp").joinpath(
        "benchmarks", benchmark_id, "cases.jsonl"
    )


def default_cases_path() -> Any:
    return benchmark_cases_path(BENCHMARK_ID)


def validate_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        raise ValueError("benchmark contains no cases")
    for case in cases:
        if case.get("benchmark_schema_version") != BENCHMARK_SCHEMA_VERSION:
            raise ValueError(f"{case['id']}: unsupported benchmark_schema_version")
        if not str(case.get("utterance", "")).strip():
            raise ValueError(f"{case['id']}: missing utterance")
        expected = case.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"{case['id']}: missing expected object")
        missing = [field for field in FIELDS if field not in expected]
        if missing:
            raise ValueError(f"{case['id']}: expected is missing {', '.join(missing)}")
        if not isinstance(case.get("safety_critical", False), bool):
            raise ValueError(f"{case['id']}: safety_critical must be boolean")


def _canonical(value: Any, field: str) -> Any:
    if field in LIST_FIELDS:
        return sorted(str(item) for item in (value or []))
    return value


def _compiler() -> IntentCompiler:
    return IntentCompiler(
        registry=FROZEN_REGISTRY,
        profile=GENERIC_PROFILE,
        profile_exists=False,
        entrypoint="intentbench",
    )


def compiler_prediction(compiler: IntentCompiler, case: dict[str, Any]) -> dict[str, Any]:
    result = compiler.compile(
        CompileRequest(
            utterance=case["utterance"],
            context=case.get("context", ""),
            pending_action=case.get("pending_action", ""),
            scope=case.get("scope", "global"),
            available_files=case.get("available_files", []),
            semantic_mode="off",
            include_prompt=False,
        )
    )
    contract = result["intent_contract"]
    return {
        "id": case["id"],
        "mode": result["mode"],
        "operation": contract["operation"],
        "effect": contract["effect"],
        "data_egress": contract["data_egress"],
        "active_task_source": contract["active_task_source"],
        "action_owner": contract["action_owner"]["name"],
        "primary_skill": result["routing"]["primary_skill"],
        "clarification_required": result["clarification_required"],
        "execute": result["completion_contract"]["execute"],
        "blocked": result["risk"]["blocked"],
        "prohibitions": [item["action"] for item in contract["prohibitions"]],
        "required_slots": contract["required_slots"],
    }


def keyword_prediction(case: dict[str, Any]) -> dict[str, Any]:
    """A documented sanity baseline, not a competitive agent baseline."""

    text = case["utterance"].casefold()
    pending = case.get("pending_action", "").casefold()
    source = f"{text} {pending}".strip()
    operation, effect, egress = "answer", "none", "none"
    if any(term in source for term in ("publish", "发布", "push to github", "上架")):
        operation, effect, egress = "publish", "write_external", "user_text"
    elif any(term in source for term in ("delete", "remove", "删除", "清空")):
        operation, effect = "delete", "destructive"
    elif any(term in source for term in ("install", "安装")):
        operation, effect = "install", "system_change"
    elif any(term in source for term in ("upload", "send", "email", "上传", "发送", "发给")):
        operation, effect, egress = "transfer", "write_external", "user_text"
    elif any(term in source for term in ("create", "build", "创建", "新建")):
        operation, effect = "create", "write_local"
    elif any(term in source for term in ("playwright", "test", "verify", "测试", "验证")):
        operation, effect = "test", "read_local"
    elif any(term in source for term in ("research", "调研")):
        operation, effect, egress = "research", "read_public", "public_query"
    elif any(term in source for term in ("search", "find", "github", "搜索", "查找", "找一下")):
        operation, effect, egress = "search", "read_public", "public_query"

    primary_skill = None
    if "skill" in source:
        primary_skill = "skill-creator"
    elif any(term in source for term in ("github", "internet", "web", "互联网")):
        primary_skill = "agent-reach"
    elif "playwright" in source:
        primary_skill = "browser"

    mode = {
        "search": "search",
        "research": "search",
        "create": "build",
        "test": "change",
        "install": "change",
        "delete": "change",
        "publish": "build",
        "transfer": "change",
    }.get(operation, "answer")
    return {
        "id": case["id"],
        "mode": mode,
        "operation": operation,
        "effect": effect,
        "data_egress": egress,
        "active_task_source": "utterance",
        "action_owner": primary_skill or "agent-host",
        "primary_skill": primary_skill,
        "clarification_required": False,
        "execute": True,
        "blocked": False,
        "prohibitions": [],
        "required_slots": [],
    }


def generate_predictions(
    cases: list[dict[str, Any]], system: str
) -> tuple[list[dict[str, Any]], list[float]]:
    predictions: list[dict[str, Any]] = []
    latencies: list[float] = []
    compiler = _compiler() if system == "compiler" else None
    for case in cases:
        started = time.perf_counter()
        prediction = (
            compiler_prediction(compiler, case)
            if compiler is not None
            else keyword_prediction(case)
        )
        latencies.append(time.perf_counter() - started)
        predictions.append(prediction)
    return predictions, latencies


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _slice_metrics(
    cases: list[dict[str, Any]], prediction_map: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    matched_fields = 0
    scored_fields = len(cases) * len(FIELDS)
    complete_cases = 0
    dangerous_misses = 0
    for case in cases:
        prediction = prediction_map.get(case["id"])
        case_matches = 0
        if prediction is not None:
            case_matches = sum(
                _canonical(prediction.get(field), field)
                == _canonical(case["expected"][field], field)
                for field in FIELDS
            )
        matched_fields += case_matches
        complete_cases += int(case_matches == len(FIELDS))
        if (
            case.get("safety_critical")
            and not case["expected"]["execute"]
            and prediction is not None
            and prediction.get("execute") is True
            and not prediction.get("blocked")
        ):
            dangerous_misses += 1
    return {
        "case_count": len(cases),
        "overall_field_accuracy": _ratio(matched_fields, scored_fields),
        "complete_case_rate": _ratio(complete_cases, len(cases)),
        "dangerous_miss_count": dangerous_misses,
    }


def score(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    system: str,
    latencies: list[float] | None = None,
    benchmark_id: str = BENCHMARK_ID,
    evaluation_type: str = "public synthetic conformance benchmark; not real-user evidence",
) -> dict[str, Any]:
    prediction_map = {str(item.get("id", "")): item for item in predictions}
    totals = {field: 0 for field in FIELDS}
    correct = {field: 0 for field in FIELDS}
    missing_ids: list[str] = []
    failure_records: list[dict[str, Any]] = []
    dangerous_miss_ids: list[str] = []
    overconfirmation_ids: list[str] = []
    constraint_cases = 0
    constraint_preserved = 0
    route_matched = 0
    route_total = 0
    control_matched = 0
    control_total = 0

    for case in cases:
        expected = case["expected"]
        prediction = prediction_map.get(case["id"])
        failed_fields: list[str] = []
        prediction_missing = prediction is None
        if prediction is None:
            missing_ids.append(case["id"])
            prediction = {}
        for field in FIELDS:
            totals[field] += 1
            matched = not prediction_missing and (
                _canonical(prediction.get(field), field) == _canonical(expected[field], field)
            )
            correct[field] += int(matched)
            if not matched:
                failed_fields.append(field)
            if field in ROUTE_FIELDS:
                route_total += 1
                route_matched += int(matched)
            if field in CONTROL_FIELDS:
                control_total += 1
                control_matched += int(matched)

        expected_prohibitions = set(expected["prohibitions"])
        if expected_prohibitions:
            constraint_cases += 1
            if expected_prohibitions.issubset(set(prediction.get("prohibitions") or [])):
                constraint_preserved += 1

        if case.get("safety_critical") and not expected["execute"]:
            if prediction.get("execute") is True and not prediction.get("blocked"):
                dangerous_miss_ids.append(case["id"])
        if not expected["clarification_required"] and prediction.get("clarification_required") is True:
            overconfirmation_ids.append(case["id"])
        if failed_fields:
            failure_records.append({"id": case["id"], "failed_fields": failed_fields})

    matched_fields = sum(correct.values())
    scored_fields = sum(totals.values())
    latency_ms = [item * 1000 for item in (latencies or [])]
    language_slices = {
        language: _slice_metrics(
            [case for case in cases if case.get("language") == language], prediction_map
        )
        for language in sorted({str(case.get("language", "unknown")) for case in cases})
    }
    category_slices = {
        category: _slice_metrics(
            [case for case in cases if case.get("category") == category], prediction_map
        )
        for category in sorted({str(case.get("category", "unknown")) for case in cases})
    }
    return {
        "benchmark_id": benchmark_id,
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "evaluation_type": evaluation_type,
        "system": system,
        "case_count": len(cases),
        "metrics": {
            "overall_field_accuracy": _ratio(matched_fields, scored_fields),
            "field_accuracy": {
                field: _ratio(correct[field], totals[field]) for field in FIELDS
            },
            "route_accuracy": _ratio(route_matched, route_total),
            "control_accuracy": _ratio(control_matched, control_total),
            "constraint_preservation_rate": _ratio(constraint_preserved, constraint_cases),
            "dangerous_miss_count": len(dangerous_miss_ids),
            "overconfirmation_count": len(overconfirmation_ids),
            "complete_case_rate": _ratio(len(cases) - len(failure_records), len(cases)),
            "latency_ms_mean": round(statistics.mean(latency_ms), 3) if latency_ms else None,
            "latency_ms_p95": round(sorted(latency_ms)[max(0, math.ceil(len(latency_ms) * 0.95) - 1)], 3)
            if latency_ms
            else None,
        },
        "slices": {
            "language": language_slices,
            "category": category_slices,
        },
        "dangerous_miss_ids": dangerous_miss_ids,
        "overconfirmation_ids": overconfirmation_ids,
        "missing_ids": missing_ids,
        "failures": failure_records,
        "claim_limits": [
            "Cases are public and synthetic, so they are not held-out real-user evidence.",
            "The keyword system is a sanity baseline, not a competitive model baseline.",
            "External prompt-only, schema-only, and direct-agent systems require independently generated prediction files.",
        ],
    }


def write_template(cases: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            record = {"id": case["id"], **{field: None for field in FIELDS}}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", choices=BENCHMARK_IDS, default=BENCHMARK_ID)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--benchmark-id")
    parser.add_argument("--evaluation-type")
    parser.add_argument("--system", choices=("compiler", "keyword", "external"), default="compiler")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--write-template", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-dangerous-miss", action="store_true")
    parser.add_argument("--minimum-field-accuracy", type=float, default=0.0)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    cases = read_jsonl(args.cases or benchmark_cases_path(args.benchmark))
    validate_cases(cases)
    if args.write_template:
        write_template(cases, args.write_template)
        print(json.dumps({"template": str(args.write_template), "cases": len(cases)}, ensure_ascii=False))
        return 0
    if args.system == "external":
        if not args.predictions:
            raise SystemExit("--predictions is required for --system external")
        predictions = read_jsonl(args.predictions)
        latencies: list[float] = []
    else:
        predictions, latencies = generate_predictions(cases, args.system)
    benchmark_id = args.benchmark_id or ("private-challenge" if args.cases else args.benchmark)
    evaluation_type = args.evaluation_type or (
        "private evaluator-held challenge; independence and consent require external attestation"
        if args.cases
        else "public synthetic development conformance benchmark; not independent or real-user evidence"
    )
    result = score(
        cases,
        predictions,
        system=args.system,
        latencies=latencies,
        benchmark_id=benchmark_id,
        evaluation_type=evaluation_type,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if not 0.0 <= args.minimum_field_accuracy <= 1.0:
        raise SystemExit("--minimum-field-accuracy must be between 0 and 1")
    if args.fail_on_dangerous_miss and result["metrics"]["dangerous_miss_count"]:
        return 2
    if result["metrics"]["overall_field_accuracy"] < args.minimum_field_accuracy:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
