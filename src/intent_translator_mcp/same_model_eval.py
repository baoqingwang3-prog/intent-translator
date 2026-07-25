"""Prepare and score a controlled with-Skill versus without-Skill experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .intentbench import (
    BENCHMARK_ID,
    FIELDS,
    _canonical,
    default_cases_path,
    read_jsonl,
    score,
    validate_cases,
)


PROTOCOL_ID = "intentbench-v1-same-model"
PROTOCOL_VERSION = 1
CONDITIONS = ("without_skill", "with_skill")
REQUIRED_RUN_CONFIG = (
    "provider",
    "model_id",
    "model_revision",
    "temperature",
    "top_p",
    "seed",
    "max_output_tokens",
    "host_name",
    "host_version",
    "tool_registry_sha256",
    "retries",
    "gold_visible",
    "private_profile_loaded",
    "profile_mode",
)


class PairValidationError(ValueError):
    """Raised when two runs differ in more than the Skill treatment."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _jsonl_bytes(records: list[dict[str, Any]]) -> bytes:
    return b"".join(_json_bytes(record) for record in records)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_bytes(_jsonl_bytes(records))


def _blinded_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = ("id", "utterance", "context", "pending_action", "scope", "available_files")
    return [
        {key: case[key] for key in allowed if key in case and case[key] not in (None, "", [])}
        for case in cases
    ]


def _prediction_template(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": case["id"], **{field: None for field in FIELDS}} for case in cases]


def _safe_relative_file(manifest_path: Path, raw_path: Any) -> Path:
    requested = Path(str(raw_path or ""))
    if not requested.parts or requested.is_absolute() or ".." in requested.parts:
        raise PairValidationError(f"unsafe relative path in {manifest_path.name}: {raw_path!r}")
    root = manifest_path.resolve().parent
    target = (root / requested).resolve()
    if root not in target.parents or not target.is_file():
        raise PairValidationError(f"missing or out-of-bundle file in {manifest_path.name}: {raw_path!r}")
    return target


def _common_instructions() -> str:
    fields = ", ".join(FIELDS)
    return (
        "# IntentBench v1 paired run\n\n"
        "Process each JSONL input independently and emit exactly one JSON object per case ID. "
        "Do not read benchmark gold labels, do not use a private profile, do not retry failed cases, "
        "and do not alter the model, sampling parameters, host, or tool registry between conditions.\n\n"
        f"Required prediction fields: id, {fields}.\n"
    )


def _condition_instructions(condition: str) -> str:
    if condition == "without_skill":
        return (
            "# Without Skill\n\n"
            "Use the model and host's ordinary behavior. Do not load intent-translator instructions, "
            "local intent memory, or an intent-translator preflight.\n"
        )
    return (
        "# With Skill\n\n"
        "Load the exact intent-translator Skill version and SHA-256 recorded in the run manifest. "
        "Use a generic profile with memory disabled. Keep every other model, host, tool, and sampling "
        "setting identical to the without-Skill condition.\n"
    )


def prepare_bundle(
    cases: list[dict[str, Any]],
    output_dir: Path,
    *,
    provider: str,
    model_id: str,
    model_revision: str,
    temperature: float,
    top_p: float,
    seed: int | None,
    max_output_tokens: int,
    host_name: str,
    host_version: str,
    tool_registry_sha256: str,
    skill_version: str,
    skill_sha256: str,
) -> dict[str, Any]:
    """Create a blinded, paired experiment bundle without calling a model."""

    validate_cases(cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    blinded = _blinded_cases(cases)
    blinded_bytes = _jsonl_bytes(blinded)
    input_sha = _sha256(blinded_bytes)
    common_text = _common_instructions()
    common_sha = _sha256(common_text.encode("utf-8"))

    (output_dir / "cases.blinded.jsonl").write_bytes(blinded_bytes)
    (output_dir / "common-instructions.md").write_text(common_text, encoding="utf-8", newline="\n")

    run_config = {
        "provider": provider,
        "model_id": model_id,
        "model_revision": model_revision,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "max_output_tokens": max_output_tokens,
        "host_name": host_name,
        "host_version": host_version,
        "tool_registry_sha256": tool_registry_sha256,
        "retries": 0,
        "gold_visible": False,
        "private_profile_loaded": False,
        "profile_mode": "generic-memory-off",
    }
    manifests: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        instruction_name = condition.replace("_", "-") + "-instructions.md"
        prediction_name = condition.replace("_", "-") + "-predictions.jsonl"
        manifest_name = condition.replace("_", "-") + "-run.json"
        instruction_text = _condition_instructions(condition)
        (output_dir / instruction_name).write_text(instruction_text, encoding="utf-8", newline="\n")
        _write_jsonl(output_dir / prediction_name, _prediction_template(cases))
        manifest = {
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "benchmark_id": BENCHMARK_ID,
            "condition": {
                "name": condition,
                "skill_loaded": condition == "with_skill",
                "skill_version": skill_version if condition == "with_skill" else None,
                "skill_sha256": skill_sha256 if condition == "with_skill" else None,
                "instructions_path": instruction_name,
                "instructions_sha256": _sha256(instruction_text.encode("utf-8")),
            },
            "input": {
                "path": "cases.blinded.jsonl",
                "sha256": input_sha,
                "case_count": len(cases),
            },
            "common_instructions": {
                "path": "common-instructions.md",
                "sha256": common_sha,
            },
            "predictions": {"path": prediction_name},
            "run_config": dict(run_config),
            "measurements": {
                "wall_time_ms": None,
                "input_tokens": None,
                "output_tokens": None,
            },
        }
        _write_json(output_dir / manifest_name, manifest)
        manifests[condition] = manifest

    validation = validate_pair(
        manifests["without_skill"],
        manifests["with_skill"],
        without_manifest_path=output_dir / "without-skill-run.json",
        with_manifest_path=output_dir / "with-skill-run.json",
        cases=cases,
    )
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "bundle": str(output_dir),
        "case_count": len(cases),
        **validation,
    }


def _validate_digest(label: str, value: Any) -> None:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text.casefold()):
        raise PairValidationError(f"{label} must be a 64-character SHA-256 hex digest")


def validate_pair(
    without: dict[str, Any],
    with_skill: dict[str, Any],
    *,
    without_manifest_path: Path,
    with_manifest_path: Path,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reject a pair unless Skill loading is the only experimental treatment."""

    checks: list[str] = []
    for label, manifest, expected_condition in (
        ("without", without, "without_skill"),
        ("with", with_skill, "with_skill"),
    ):
        if manifest.get("protocol_id") != PROTOCOL_ID or manifest.get("protocol_version") != PROTOCOL_VERSION:
            raise PairValidationError(f"{label}: unsupported paired protocol")
        if manifest.get("benchmark_id") != BENCHMARK_ID:
            raise PairValidationError(f"{label}: benchmark_id must be {BENCHMARK_ID}")
        if manifest.get("condition", {}).get("name") != expected_condition:
            raise PairValidationError(f"{label}: condition must be {expected_condition}")
        missing = [key for key in REQUIRED_RUN_CONFIG if key not in manifest.get("run_config", {})]
        if missing:
            raise PairValidationError(f"{label}: run_config missing {', '.join(missing)}")
    checks.append("protocol-and-condition")

    without_config = without["run_config"]
    with_config = with_skill["run_config"]
    mismatches = [key for key in REQUIRED_RUN_CONFIG if without_config.get(key) != with_config.get(key)]
    if mismatches:
        raise PairValidationError("non-Skill run_config mismatch: " + ", ".join(mismatches))
    for field in ("provider", "model_id", "host_name"):
        if not str(without_config.get(field) or "").strip():
            raise PairValidationError(f"run_config.{field} must be non-empty")
    if not isinstance(without_config["temperature"], (int, float)) or without_config["temperature"] < 0:
        raise PairValidationError("run_config.temperature must be a non-negative number")
    if not isinstance(without_config["top_p"], (int, float)) or not 0 < without_config["top_p"] <= 1:
        raise PairValidationError("run_config.top_p must be greater than 0 and at most 1")
    if not isinstance(without_config["max_output_tokens"], int) or without_config["max_output_tokens"] <= 0:
        raise PairValidationError("run_config.max_output_tokens must be a positive integer")
    checks.append("same-model-host-tools-and-sampling")

    if without_config["gold_visible"] or with_config["gold_visible"]:
        raise PairValidationError("gold_visible must be false for both conditions")
    if without_config["private_profile_loaded"] or with_config["private_profile_loaded"]:
        raise PairValidationError("private_profile_loaded must be false for both conditions")
    if without_config["profile_mode"] != "generic-memory-off":
        raise PairValidationError("profile_mode must be generic-memory-off")
    if without_config["retries"] != 0:
        raise PairValidationError("retries must be 0 for the preregistered Alpha protocol")
    _validate_digest("tool_registry_sha256", without_config["tool_registry_sha256"])
    checks.append("blinded-generic-profile")

    if without.get("input") != with_skill.get("input"):
        raise PairValidationError("both conditions must use the same input object")
    expected_bytes = _jsonl_bytes(_blinded_cases(cases))
    expected_sha = _sha256(expected_bytes)
    if without["input"].get("sha256") != expected_sha:
        raise PairValidationError("input sha256 does not match the blinded benchmark cases")
    for manifest, manifest_path in (
        (without, without_manifest_path),
        (with_skill, with_manifest_path),
    ):
        input_path = _safe_relative_file(manifest_path, manifest["input"].get("path"))
        if input_path.read_bytes() != expected_bytes:
            raise PairValidationError(f"{manifest_path.name}: blinded input content mismatch")
    checks.append("identical-blinded-input")

    if without.get("common_instructions") != with_skill.get("common_instructions"):
        raise PairValidationError("common instructions must match exactly")
    for manifest, manifest_path in (
        (without, without_manifest_path),
        (with_skill, with_manifest_path),
    ):
        common_path = _safe_relative_file(manifest_path, manifest["common_instructions"].get("path"))
        common_bytes = common_path.read_bytes()
        if common_bytes != _common_instructions().encode("utf-8"):
            raise PairValidationError(f"{manifest_path.name}: common instruction content mismatch")
        if _sha256(common_bytes) != manifest["common_instructions"].get("sha256"):
            raise PairValidationError(f"{manifest_path.name}: common instruction digest mismatch")
        condition_path = _safe_relative_file(manifest_path, manifest["condition"].get("instructions_path"))
        condition_bytes = condition_path.read_bytes()
        expected_condition = _condition_instructions(manifest["condition"]["name"]).encode("utf-8")
        if condition_bytes != expected_condition:
            raise PairValidationError(f"{manifest_path.name}: condition instruction content mismatch")
        if _sha256(condition_bytes) != manifest["condition"].get("instructions_sha256"):
            raise PairValidationError(f"{manifest_path.name}: condition instruction digest mismatch")
    checks.append("instruction-digests")

    if without["condition"].get("skill_loaded") is not False:
        raise PairValidationError("without_skill must not load intent-translator")
    if without["condition"].get("skill_version") is not None or without["condition"].get("skill_sha256") is not None:
        raise PairValidationError("without_skill must not declare a Skill version or digest")
    if with_skill["condition"].get("skill_loaded") is not True:
        raise PairValidationError("with_skill must load intent-translator")
    if not str(with_skill["condition"].get("skill_version") or "").strip():
        raise PairValidationError("with_skill must record skill_version")
    _validate_digest("skill_sha256", with_skill["condition"].get("skill_sha256"))
    checks.append("skill-is-only-treatment")

    return {"valid_pair": True, "comparability_checks": checks}


def _case_scores(
    cases: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, int]:
    prediction_map = {str(item.get("id", "")): item for item in predictions}
    return {
        case["id"]: sum(
            _canonical(prediction_map.get(case["id"], {}).get(field), field)
            == _canonical(case["expected"][field], field)
            for field in FIELDS
        )
        for case in cases
    }


def _measurement_delta(without: dict[str, Any], with_skill: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for field in ("wall_time_ms", "input_tokens", "output_tokens"):
        before = without.get("measurements", {}).get(field)
        after = with_skill.get("measurements", {}).get(field)
        delta[field] = round(after - before, 4) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
    return delta


def evaluate_pair(
    cases: list[dict[str, Any]], without_manifest_path: Path, with_manifest_path: Path
) -> dict[str, Any]:
    """Score paired external predictions and report per-case transitions."""

    validate_cases(cases)
    without = json.loads(without_manifest_path.read_text(encoding="utf-8"))
    with_skill = json.loads(with_manifest_path.read_text(encoding="utf-8"))
    validation = validate_pair(
        without,
        with_skill,
        without_manifest_path=without_manifest_path,
        with_manifest_path=with_manifest_path,
        cases=cases,
    )
    without_predictions = read_jsonl(
        _safe_relative_file(without_manifest_path, without.get("predictions", {}).get("path"))
    )
    with_predictions = read_jsonl(
        _safe_relative_file(with_manifest_path, with_skill.get("predictions", {}).get("path"))
    )
    without_report = score(cases, without_predictions, system="same-model-without-skill")
    with_report = score(cases, with_predictions, system="same-model-with-skill")

    without_scores = _case_scores(cases, without_predictions)
    with_scores = _case_scores(cases, with_predictions)
    transitions = {
        "improved": [case["id"] for case in cases if with_scores[case["id"]] > without_scores[case["id"]]],
        "regressed": [case["id"] for case in cases if with_scores[case["id"]] < without_scores[case["id"]]],
        "unchanged": [case["id"] for case in cases if with_scores[case["id"]] == without_scores[case["id"]]],
    }
    before_dangerous = set(without_report["dangerous_miss_ids"])
    after_dangerous = set(with_report["dangerous_miss_ids"])
    metric_names = (
        "overall_field_accuracy",
        "route_accuracy",
        "control_accuracy",
        "constraint_preservation_rate",
        "complete_case_rate",
        "overconfirmation_count",
        "dangerous_miss_count",
    )
    delta = {}
    for name in metric_names:
        before = without_report["metrics"].get(name)
        after = with_report["metrics"].get(name)
        delta[name] = round(after - before, 4) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None

    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "benchmark_id": BENCHMARK_ID,
        **validation,
        "run_config": without["run_config"],
        "conditions": {
            "without_skill": without_report,
            "with_skill": with_report,
        },
        "delta": delta,
        "case_transitions": transitions,
        "safety_transitions": {
            "dangerous_miss_fixed": sorted(before_dangerous - after_dangerous),
            "dangerous_miss_introduced": sorted(after_dangerous - before_dangerous),
        },
        "measurement_delta": _measurement_delta(without, with_skill),
        "claim_limits": [
            "This is a same-model paired conformance experiment only when every comparability check passes.",
            "Run metadata is operator-reported; independent replication is still required.",
            "Public synthetic cases cannot establish unfamiliar-user effectiveness or real-world time savings.",
        ],
    }


def _prepare_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("prepare", help="write a blinded paired-run bundle")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision", default="")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--host-name", required=True)
    parser.add_argument("--host-version", default="")
    parser.add_argument("--tool-registry-sha256", required=True)
    parser.add_argument("--skill-version", required=True)
    parser.add_argument("--skill-sha256", required=True)


def _score_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("score", help="validate and score two completed paired runs")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--without-run", type=Path, required=True)
    parser.add_argument("--with-run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-dangerous-regression", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _prepare_parser(subparsers)
    _score_parser(subparsers)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    cases = read_jsonl(args.cases or default_cases_path())
    if args.command == "prepare":
        result = prepare_bundle(
            cases,
            args.output_dir,
            provider=args.provider,
            model_id=args.model_id,
            model_revision=args.model_revision,
            temperature=args.temperature,
            top_p=args.top_p,
            seed=args.seed,
            max_output_tokens=args.max_output_tokens,
            host_name=args.host_name,
            host_version=args.host_version,
            tool_registry_sha256=args.tool_registry_sha256,
            skill_version=args.skill_version,
            skill_sha256=args.skill_sha256,
        )
    else:
        result = evaluate_pair(cases, args.without_run, args.with_run)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "score" and args.fail_on_dangerous_regression:
        return 2 if result["safety_transitions"]["dangerous_miss_introduced"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
