r"""Step 4: resident semantic server (persistent model cache).

Problem it solves: the command adapter spawns a fresh subprocess per call
and times out at 20s default; E5 initialization alone is ~39-84s. A resident
HTTP server loads the model once and answers every later request in ~250ms.

Protocol: POST /compile {"utterance","context","pending_action"} ->
SemanticProposal JSON. GET /health -> {"ready": true}.

Usage:
    python ilang_semantic_server.py --port 8766          # BGE default
    ILANG_DISTILL_EMBED_MODEL=intfloat/multilingual-e5-large \
    ILANG_DISTILL_MODEL_PATH=<dir> python ilang_semantic_server.py

Stdlib http.server only; no new dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import os
_DEFAULT_DEPS = Path.home() / ".workbuddy-ai" / "binaries" / "node" / "workspace" / "pydeps"
DEPS = Path(os.environ.get("ILANG_DISTILL_DEPS", str(_DEFAULT_DEPS)))
if DEPS.is_dir() and str(DEPS) not in sys.path:
    sys.path.append(str(DEPS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import ilang_semantic_main as semantic_main  # noqa: E402

_STATE = {"ready": False, "model": None, "error": None}


def warmup() -> None:
    """Load model + keyword compiler once; flip ready flag."""
    try:
        # keyword engine (fast)
        semantic_main._keyword_compile("warmup")
        # embedding model (slow — the whole point of this server)
        if os.environ.get("ILANG_DISTILL_SKIP_EMBED") == "1":
            _STATE["model"] = "keyword-only"
        else:
            from ilang_distill_router import get_centroids
            _STATE["model"] = os.environ.get(
                "ILANG_DISTILL_EMBED_MODEL", semantic_main and "BAAI/bge-small-zh-v1.5"
            )
            router_mod = sys.modules.get("ilang_distill_router")
            if router_mod is not None:
                router_mod.get_centroids()
        _STATE["ready"] = True
        print("server ready", flush=True)
    except Exception as exc:  # keep serving refusals/degraded, don't die
        _STATE["error"] = str(exc)[:300]
        print(f"warmup failed: {_STATE['error']}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {"ready": _STATE["ready"], "model": _STATE["model"],
                             "error": _STATE["error"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/compile":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            # step 5 requirement: malformed JSON -> graceful fallback proposal
            self._send(200, _fallback_proposal("", "malformed JSON"))
            return
        if not _STATE["ready"]:
            self._send(200, _fallback_proposal(
                str(payload.get("utterance", "")), f"model not ready: {_STATE['error']}"))
            return
        try:
            utt = str(payload.get("utterance", ""))
            if semantic_main.has_ilang_syntax(utt):
                proposal = semantic_main.ilang_proposal(payload)
                proposal["interpretation"] = "[ilang] " + proposal.get("interpretation", "")
            else:
                proposal = semantic_main.cascade_proposal(payload)
        except Exception as exc:
            proposal = _fallback_proposal(
                str(payload.get("utterance", "")), f"cascade error: {exc}")
        self._send(200, proposal)


def _fallback_proposal(utterance: str, reason: str) -> dict:
    """Degrade gracefully: abstain, flag clarification. Never guesses."""
    return {
        "normalized_goal": utterance[:1000],
        "interpretation": f"server fallback: {reason}",
        "mode": None,
        "assumptions": [],
        "alternatives": [],
        "confidence": 0.1,
        "primary_skill": None,
        "risk_hints": [],
        "clarification_recommended": True,
        "language": "zh",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    # warm in background thread so /health is up immediately
    import threading
    threading.Thread(target=warmup, daemon=True).start()
    print(f"listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
