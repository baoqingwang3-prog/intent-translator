"""Prepare blinded evaluator-held challenge bundles without publishing gold labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .intentbench import read_jsonl, validate_cases


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
PRIVATE_KEYS = {"expected", "safety_critical", "notes", "gold", "label"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _slice_counts(cases: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(case.get(key, "unspecified")) for case in cases).items()))


def prepare_private_challenge(
    cases: list[dict[str, Any]],
    output_dir: Path,
    *,
    challenge_id: str,
    sampling_rule: str,
    independent_evaluator: bool = False,
) -> dict[str, Any]:
    """Write a gold-free input bundle and a metadata-only manifest."""
    if not SAFE_ID.fullmatch(challenge_id):
        raise ValueError("challenge_id must be a 3-64 character lowercase slug")
    if not sampling_rule.strip():
        raise ValueError("sampling_rule is required")
    validate_cases(cases)
    output_dir.mkdir(parents=True, exist_ok=True)

    blinded = [
        {key: value for key, value in case.items() if key not in PRIVATE_KEYS}
        for case in cases
    ]
    blinded_path = output_dir / "cases.blinded.jsonl"
    with blinded_path.open("w", encoding="utf-8", newline="\n") as handle:
        for case in blinded:
            handle.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n")

    manifest = {
        "schema_version": 1,
        "challenge_id": challenge_id,
        "evidence_class": (
            "private-independent-challenge"
            if independent_evaluator
            else "private-challenge-protocol"
        ),
        "independent_evaluator_declared": independent_evaluator,
        "case_count": len(cases),
        "sampling_rule": sampling_rule.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gold_sha256": _sha256(cases),
        "blinded_sha256": _sha256(blinded),
        "slices": {
            "language": _slice_counts(cases, "language"),
            "role": _slice_counts(cases, "role"),
            "category": _slice_counts(cases, "category"),
        },
        "contains_utterances": False,
        "contains_gold_labels": False,
        "claim_limits": [
            "The manifest does not prove evaluator independence, participant consent, or correct sampling.",
            "Keep the original gold file outside the public repository.",
            "Publish only aggregate metrics unless every utterance has explicit publication consent.",
        ],
    }
    manifest_path = output_dir / "challenge-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "blinded_cases": str(blinded_path.resolve()),
        "manifest": str(manifest_path.resolve()),
        "case_count": len(cases),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--challenge-id", required=True)
    parser.add_argument("--sampling-rule", required=True)
    parser.add_argument("--independent-evaluator", action="store_true")
    args = parser.parse_args()
    result = prepare_private_challenge(
        read_jsonl(args.cases),
        args.output_dir,
        challenge_id=args.challenge_id,
        sampling_rule=args.sampling_rule,
        independent_evaluator=args.independent_evaluator,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
