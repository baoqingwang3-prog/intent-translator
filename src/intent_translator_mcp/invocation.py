"""Create privacy-bounded evidence that the local preflight tool was called."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .models import CompileRequest


def build_invocation_receipt(
    request: CompileRequest,
    envelope: dict[str, Any],
    *,
    tool: str = "intent_compile",
) -> dict[str, Any]:
    request_payload = request.model_dump(mode="json")
    request_sha256 = hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    runtime = envelope.get("runtime_status", {})
    return {
        "schema_version": 1,
        "receipt_id": "preflight-" + uuid.uuid4().hex[:20],
        "preflight_observed": True,
        "host": os.environ.get("INTENT_TRANSLATOR_HOST", "unspecified").strip() or "unspecified",
        "tool": tool,
        "request_sha256": request_sha256,
        "decision": envelope.get("tool_gateway", {}).get("decision", "unknown"),
        "runtime_version": runtime.get("versions", {}).get("actual_runtime"),
        "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "enforcement_claim": "preflight-observed-not-host-enforced",
    }
