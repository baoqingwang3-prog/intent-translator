"""Record consented Alpha trial metrics without storing participant utterances."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVENTS = ("install", "onboarding", "request", "correction", "receipt", "uninstall")
STATUSES = ("pass", "fail", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def init_trial(path: Path, *, real_participant: bool, consent_confirmed: bool) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "trial_id": "trial-" + uuid.uuid4().hex[:16],
        "participant_id": "participant-" + uuid.uuid4().hex[:12],
        "real_participant": bool(real_participant),
        "consent_confirmed": bool(consent_confirmed),
        "created_at": _now(),
        "updated_at": _now(),
        "events": [],
        "metrics": {
            "dangerous_confirmation_misses": 0,
            "cross_profile_contamination": 0,
            "creator_default_leakage": 0,
            "wrong_routes": 0,
            "invalid_questions": 0,
            "correction_recurrence": 0,
        },
        "privacy": {
            "raw_utterances_stored": False,
            "free_text_notes_allowed": False,
            "deletion_command": "intent-translator-trial delete --confirm DELETE-TRIAL-RECORD",
        },
    }
    _write(path, payload)
    return payload


def record_trial_event(
    path: Path,
    *,
    event: str,
    status: str,
    duration_seconds: float | None = None,
    dangerous_confirmation_misses: int = 0,
    cross_profile_contamination: int = 0,
    creator_default_leakage: int = 0,
    wrong_routes: int = 0,
    invalid_questions: int = 0,
    correction_recurrence: int = 0,
) -> dict[str, Any]:
    if event not in EVENTS:
        raise ValueError(f"unsupported event: {event}")
    if status not in STATUSES:
        raise ValueError(f"unsupported status: {status}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = {"event": event, "status": status, "recorded_at": _now()}
    if duration_seconds is not None:
        entry["duration_seconds"] = max(0.0, round(float(duration_seconds), 3))
    payload["events"].append(entry)
    increments = {
        "dangerous_confirmation_misses": dangerous_confirmation_misses,
        "cross_profile_contamination": cross_profile_contamination,
        "creator_default_leakage": creator_default_leakage,
        "wrong_routes": wrong_routes,
        "invalid_questions": invalid_questions,
        "correction_recurrence": correction_recurrence,
    }
    for key, value in increments.items():
        payload["metrics"][key] = int(payload["metrics"].get(key, 0)) + max(0, int(value))
    payload["updated_at"] = _now()
    _write(path, payload)
    return payload


def summarize_trials(paths: list[Path]) -> dict[str, Any]:
    sessions = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    completed = 0
    totals = {
        "dangerous_confirmation_misses": 0,
        "cross_profile_contamination": 0,
        "creator_default_leakage": 0,
        "wrong_routes": 0,
        "invalid_questions": 0,
        "correction_recurrence": 0,
    }
    for session in sessions:
        passed = {item["event"] for item in session.get("events", []) if item.get("status") == "pass"}
        completed += int(set(EVENTS).issubset(passed))
        for key in totals:
            totals[key] += int(session.get("metrics", {}).get(key, 0))
    real_candidates = [
        item for item in sessions if item.get("real_participant") and item.get("consent_confirmed")
    ]
    return {
        "schema_version": 1,
        "participant_count": len(sessions),
        "completed_participant_count": completed,
        **totals,
        "evidence_class": (
            "real-user-self-reported-candidate"
            if real_candidates
            else "synthetic-or-unconfirmed-trial-protocol"
        ),
        "raw_utterances_stored": False,
        "claim_limits": [
            "The tool records protocol metrics; it does not create independent participants.",
            "Until 3-5 real participants complete the protocol, real-user evidence remains pending.",
        ],
    }


def delete_trial(path: Path, *, confirm: str) -> dict[str, Any]:
    if confirm != "DELETE-TRIAL-RECORD":
        raise ValueError("delete requires --confirm DELETE-TRIAL-RECORD")
    existed = path.exists()
    if existed:
        path.unlink()
    return {"deleted": existed, "path": str(path.resolve())}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--session", type=Path, required=True)
    init.add_argument("--real-participant", action="store_true")
    init.add_argument("--consent-confirmed", action="store_true")
    record = subparsers.add_parser("record")
    record.add_argument("--session", type=Path, required=True)
    record.add_argument("--event", choices=EVENTS, required=True)
    record.add_argument("--status", choices=STATUSES, required=True)
    record.add_argument("--duration-seconds", type=float)
    summary = subparsers.add_parser("summary")
    summary.add_argument("--sessions", type=Path, nargs="+", required=True)
    delete = subparsers.add_parser("delete")
    delete.add_argument("--session", type=Path, required=True)
    delete.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.command == "init":
        result = init_trial(
            args.session,
            real_participant=args.real_participant,
            consent_confirmed=args.consent_confirmed,
        )
    elif args.command == "record":
        result = record_trial_event(
            args.session,
            event=args.event,
            status=args.status,
            duration_seconds=args.duration_seconds,
        )
    elif args.command == "summary":
        result = summarize_trials(args.sessions)
    else:
        result = delete_trial(args.session, confirm=args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
