"""Local web Studio for inspecting and exercising the intent compiler."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from .core import IntentCompiler, _candidate_skill_dirs
from .models import CompileRequest
from .onboarding import generic_profile
from .runtime_status import build_runtime_status
from .version import __version__


MAX_REQUEST_BYTES = 1_000_000
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
}


def studio_asset_dir() -> Path:
    return Path(__file__).resolve().parent / "studio_assets"


def _runtime_payload(compiler: IntentCompiler, *, entrypoint: str = "studio") -> dict[str, Any]:
    runtime = build_runtime_status(
        actual_version=__version__,
        profile=compiler.profile if compiler.profile_exists else None,
        entrypoint=entrypoint,
        skill_dirs=_candidate_skill_dirs(),
    )
    return {
        "state": runtime["state"],
        "restart_required": runtime["restart_required"],
        "entrypoint": runtime["entrypoint"],
        "versions": runtime["versions"],
        "message": runtime["message"],
    }


def build_status_payload() -> dict[str, Any]:
    compiler = IntentCompiler(entrypoint="studio")
    return {
        "compiler_connected": True,
        "host_connection": "not-verified",
        "runtime": _runtime_payload(compiler),
        "data": {
            "mode": "local",
            "location": "local-app-data",
            "exact_path_exposed": False,
        },
        "semantic_enhancement": {
            "configured": compiler.semantic_adapter is not None,
            "external": bool(compiler.semantic_adapter and compiler.semantic_adapter.external),
        },
        "personalization": "local-profile" if compiler.profile_exists else "generic",
    }


def _reason_label(reason: str) -> str:
    labels = {
        "external action lacks explicit authorization": "外部动作尚未得到具体授权",
        "irreversible action lacks explicit authorization": "不可逆动作尚未得到具体授权",
        "sensitive external transfer lacks explicit authorization": "敏感内容外发尚未得到具体授权",
        "high-stakes request requires verified evidence and bounded guidance": "高影响请求需要核验证据并限制范围",
        "authorization is denied": "当前动作未获授权",
    }
    return labels.get(reason, reason)


def _memory_sources(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in envelope.get("memories", [])[:5]:
        sources.append(
            {
                "kind": "memory",
                "id": item.get("id"),
                "scope": item.get("scope", "global"),
                "stale": bool(item.get("stale", False)),
            }
        )
    for item in envelope.get("corrections", [])[:5]:
        sources.append(
            {
                "kind": "correction",
                "id": item.get("id"),
                "scope": item.get("scope", "global"),
                "severity": item.get("severity", ""),
            }
        )
    personalization = envelope.get("personalization_status", {})
    if personalization.get("mode") == "local-profile":
        sources.append({"kind": "local-profile", "scope": "local"})
    if envelope.get("state_status", {}).get("enabled"):
        sources.append({"kind": "task-state", "scope": "local"})
    return sources


def studio_view(envelope: dict[str, Any]) -> dict[str, Any]:
    risk = envelope.get("risk", {})
    gate = envelope.get("interpretation_gate", {})
    reasons = [_reason_label(str(item)) for item in risk.get("reasons", [])]
    if gate.get("required"):
        reasons.insert(0, "存在多个会改变结果的理解")
    if envelope.get("short_confirmation_status", {}).get("state") == "missing-specific-action":
        reasons.insert(0, "没有找到可被这句确认授权的具体上一动作")
    routing = envelope.get("routing", {})
    semantic = envelope.get("semantic", {})
    runtime = envelope.get("runtime_status", {})
    execute = bool(envelope.get("completion_contract", {}).get("execute", False))
    blocked = bool(risk.get("blocked", False))
    clarification_required = bool(envelope.get("clarification_required", False))
    mode = str(envelope.get("mode", "answer"))
    action_state = (
        "blocked"
        if blocked
        else "executable"
        if execute
        else "waiting-confirmation"
        if clarification_required
        else "answer-only"
        if mode in {"answer", "diagnose"}
        else "not-executable"
    )
    return {
        "understanding": envelope.get("normalized_goal", ""),
        "selected_skill": routing.get("primary_skill"),
        "skill_candidates": [
            {"name": item.get("name"), "score": item.get("score")}
            for item in routing.get("candidates", [])[:3]
        ],
        "source_map": envelope.get("prompt_source_map", []),
        "memory_sources": _memory_sources(envelope),
        "authorization": {
            "impact": risk.get("impact", "low"),
            "external": bool(risk.get("external", False)),
            "sensitive": bool(risk.get("sensitive", False)),
            "reversible": risk.get("reversible", "unknown"),
            "confirmation_required": clarification_required,
            "blocked": blocked,
            "execute": execute,
            "action_state": action_state,
            "constraints": envelope.get("constraints", []),
        },
        "why_ask": reasons,
        "interpretations": {
            "required": bool(gate.get("required", False)),
            "candidates": gate.get("candidates", []),
            "controls": gate.get("controls", []),
        },
        "runtime": {
            "state": runtime.get("state", "degraded"),
            "restart_required": bool(runtime.get("restart_required", False)),
            "entrypoint": runtime.get("entrypoint", "studio"),
            "host_connection": "not-verified",
            "versions": runtime.get("versions", {}),
            "message": runtime.get("message", ""),
        },
        "local_mode": {
            "active": bool(envelope.get("base_mode", {}).get("active", True)),
            "semantic_status": semantic.get("status", "unavailable"),
            "semantic_provider": semantic.get("provider"),
        },
        "debate": {
            "available": bool(envelope.get("conditional_review", {}).get("available", False)),
            "recommended": bool(envelope.get("conditional_review", {}).get("use_pua", False)),
            "full_requires_opt_in": True,
        },
        "advanced": {
            "mode": envelope.get("mode"),
            "path": envelope.get("path"),
            "confidence": envelope.get("confidence"),
            "semantic_fidelity": envelope.get("semantic_fidelity", {}),
            "short_confirmation": envelope.get("short_confirmation_status", {}),
        },
    }


def compile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "utterance",
        "context",
        "pending_action",
        "scope",
        "authorization",
        "semantic_mode",
        "allow_external_semantic",
        "allow_sensitive_semantic",
    }
    request_data = {key: value for key, value in payload.items() if key in allowed}
    request_data["include_prompt"] = False
    request = CompileRequest.model_validate(request_data)
    envelope = IntentCompiler(entrypoint="studio").compile(request)
    return studio_view(envelope)


def correction_demo_payload() -> dict[str, Any]:
    registry = {
        "skills": [
            {"name": "skill-creator", "description": "Create and validate reusable Agent Skills"}
        ],
        "errors": [],
    }
    with tempfile.TemporaryDirectory(prefix="intent-translator-studio-") as temp:
        profile = generic_profile()
        profile["profile_id"] = "synthetic-studio-demo"
        profile["memory"] = {"adapter": "sqlite", "location": str(Path(temp) / "memory.db")}
        before = IntentCompiler(
            registry=registry,
            profile=profile,
            profile_exists=True,
            entrypoint="studio-demo",
        ).compile(CompileRequest(utterance="走起", semantic_mode="off", include_prompt=False))
        corrected = copy.deepcopy(profile)
        corrected["phrase_mappings"]["走起"] = {
            "meaning": "创建并验证一个最小 Skill",
            "scope": "global",
            "match_mode": "exact",
            "confidence": "confirmed",
        }
        after = IntentCompiler(
            registry=registry,
            profile=corrected,
            profile_exists=True,
            entrypoint="studio-demo",
        ).compile(CompileRequest(utterance="走起", semantic_mode="off", include_prompt=False))
    return {
        "synthetic_profile": True,
        "before": studio_view(before),
        "after": studio_view(after),
    }


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "IntentTranslatorStudio/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name: str) -> None:
        requested = Path(name)
        segments = name.replace("\\", "/").split("/")
        requested_suffix = requested.suffix.casefold()
        if (
            not requested.parts
            or requested.is_absolute()
            or requested.drive
            or any(segment in {"", ".", ".."} for segment in segments)
            or requested_suffix not in MIME_TYPES
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        root = studio_asset_dir().resolve()
        target = (root / requested).resolve()
        target_mime_type = MIME_TYPES.get(target.suffix.casefold())
        if root not in target.parents or not target.is_file() or target_mime_type is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", target_mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(build_status_payload())
            return
        if path == "/api/demo/correction":
            self._json(correction_demo_payload())
            return
        self._asset("index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/compile":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request must be an object")
            self._json(compile_payload(payload))
        except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError, TypeError):
            self._json({"error": "invalid request"}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json({"error": "local compiler unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    allow_network: bool = False,
) -> ThreadingHTTPServer:
    if not allow_network and not _is_loopback_host(host):
        raise ValueError("Studio binds to loopback by default; pass --allow-network explicitly")
    return ThreadingHTTPServer((host, port), StudioHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow a non-loopback bind; use only on a trusted network",
    )
    args = parser.parse_args()
    try:
        server = create_server(args.host, args.port, allow_network=args.allow_network)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Intent Translator Studio: http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
