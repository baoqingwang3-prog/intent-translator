"""Export privacy-bounded execution mismatches for human-reviewed regression candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


FIELDS = (
    "mode", "operation", "effect", "data_egress", "active_task_source", "action_owner",
    "primary_skill", "clarification_required", "execute", "blocked", "prohibitions", "required_slots",
)
PRIVATE_TEXT = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"/(?:Users|home)/[^\s]+", re.I),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I),
    re.compile(r"\b(?:api[_ -]?key|password|secret|token)\b", re.I),
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_token(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return text if re.fullmatch(r"[a-z0-9_.-]{1,64}", text) else "redacted"


def export_feedback_candidates(db_path: Path, *, limit: int = 100) -> dict[str, Any]:
    path = db_path.expanduser().resolve()
    if not path.exists():
        return {"schema_version": 1, "candidate_count": 0, "candidates": [], "raw_text_included": False}
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_outcomes'"
        ).fetchone()
        if not exists:
            rows = []
        else:
            rows = connection.execute(
                """
                SELECT id, scope, utterance, expected_operation, expected_skill,
                       actual_operation, actual_skill, success, mismatch_json,
                       correction_id, created_at
                FROM execution_outcomes
                WHERE matched = 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
    finally:
        connection.close()

    candidates = []
    for row in rows:
        mismatch_fields = []
        try:
            mismatch_fields = [str(item.get("field", "")) for item in json.loads(row["mismatch_json"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        identity = f"{row['id']}:{row['created_at']}:{row['utterance']}"
        candidates.append(
            {
                "schema_version": 1,
                "candidate_id": "feedback-" + _hash(identity)[:20],
                "utterance_sha256": _hash(str(row["utterance"])),
                "scope_sha256": _hash(str(row["scope"])),
                "expected_operation": _safe_token(row["expected_operation"]),
                "expected_skill": _safe_token(row["expected_skill"]),
                "actual_operation": _safe_token(row["actual_operation"]),
                "actual_skill": _safe_token(row["actual_skill"]),
                "mismatch_fields": sorted(set(mismatch_fields)),
                "success": bool(row["success"]),
                "confirmed_correction_exists": row["correction_id"] is not None,
                "created_at": row["created_at"],
                "status": "needs-human-review",
                "publishable": False,
            }
        )
    return {
        "schema_version": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "raw_text_included": False,
        "automatic_benchmark_promotion": False,
        "claim_limits": [
            "A hash-only candidate cannot be reproduced until a human supplies a sanitized utterance.",
            "Consent and gold labels require separate human review.",
        ],
    }


def review_feedback_candidate(
    candidate: dict[str, Any],
    *,
    sanitized_utterance: str,
    expected: dict[str, Any],
    consent_to_publish: bool,
) -> dict[str, Any]:
    utterance = " ".join(sanitized_utterance.split())
    if not consent_to_publish:
        raise ValueError("publication consent is required for a public fixture candidate")
    if not utterance or len(utterance) > 1000:
        raise ValueError("sanitized_utterance must contain 1-1000 characters")
    if any(pattern.search(utterance) for pattern in PRIVATE_TEXT):
        raise ValueError("sanitized_utterance still appears to contain private data")
    clean_expected = {key: expected[key] for key in FIELDS if key in expected}
    missing_fields = [field for field in FIELDS if field not in clean_expected]
    return {
        "schema_version": 1,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "status": "reviewed-fixture-candidate",
        "utterance": utterance,
        "expected": clean_expected,
        "consent_to_publish": True,
        "publishable": not missing_fields,
        "missing_fields": missing_fields,
        "automatic_benchmark_promotion": False,
        "next_step": "independent label review, then add to a new benchmark version",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--limit", type=int, default=100)
    review = subparsers.add_parser("review")
    review.add_argument("--candidate", type=Path, required=True)
    review.add_argument("--utterance", required=True)
    review.add_argument("--expected", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--consent-to-publish", action="store_true")
    args = parser.parse_args()
    if args.command == "export":
        result = export_feedback_candidates(args.db, limit=args.limit)
    else:
        result = review_feedback_candidate(
            json.loads(args.candidate.read_text(encoding="utf-8")),
            sanitized_utterance=args.utterance,
            expected=json.loads(args.expected.read_text(encoding="utf-8")),
            consent_to_publish=args.consent_to_publish,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
