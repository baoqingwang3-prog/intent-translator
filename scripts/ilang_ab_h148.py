r"""Probe how semantic skill fields affect the compiler's H148 decision.

Each variant returns a fixed proposal through the real JSON subprocess
adapter. The live semantic command is reported separately for comparison.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import adapter_from_env, semantic_payload  # noqa: E402

PY = sys.executable
MAIN = str(HERE / "ilang_semantic_main.py")

UTT = "查一下机票价格，不要帮我把钱付了"

base = {
    "normalized_goal": "查一下机票价格",
    "interpretation": "Cascaded router: mode=search via clear-primary (conf=0.85).",
    "mode": "search",
    "assumptions": [],
    "confidence": 0.85,
    "risk_hints": [],
    "clarification_recommended": False,
    "language": "zh",
}


def run(primary: str | None, alternatives: list[str]) -> dict:
    payload = {**base, "primary_skill": primary, "alternatives": alternatives}
    # Consume the compiler's JSON request and emit this variant's proposal.
    # An argv value keeps the fixture local and avoids shell interpolation.
    argv = [PY, "-B", "-c",
            "import json, sys; json.load(sys.stdin); print(sys.argv[1])",
            json.dumps(payload, ensure_ascii=False)]
    adapter = adapter_from_env({
        "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps(argv),
        "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "120",
    })
    with tempfile.TemporaryDirectory(prefix="ilang-ab-") as temporary:
        profile = Path(temporary) / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1, "profile_id": "ab", "language": "zh-CN",
            "phrase_mappings": {}, "memory": {"adapter": "none", "location": ""},
        }, ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temporary) / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(Path(temporary) / "memory.db"),
        }, clear=False):
            compiler = IntentCompiler(entrypoint="ab", registry={"skills": [], "errors": []},
                                      semantic_adapter=adapter)
            return compiler.compile(CompileRequest(
                utterance=UTT, context="", pending_action="",
                semantic_mode="required", include_prompt=False))


def live_proposal() -> dict:
    adapter = adapter_from_env({
        "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps([PY, "-B", MAIN]),
        "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "120",
    })
    return adapter.interpret(semantic_payload(
        utterance=UTT, context="", pending_action="",
        deterministic={"normalized_goal": UTT}, skills=[],
    )).model_dump()


def main() -> int:
    for name, primary, alts in [
        ("clean", None, []),
        ("primary", "agent-reach", []),
        ("alts-only", None, ["agent-reach", "smart-search"]),
    ]:
        env = run(primary, alts)
        cc = env["completion_contract"]
        print(f"{name:10s} execute={cc['execute']} mode={env['mode']} "
              f"egress={env['intent_contract']['data_egress']} skill={env['routing']['primary_skill']}")

    proposal = live_proposal()
    print("subprocess proposal:", json.dumps(
        {k: proposal.get(k) for k in ("mode", "confidence", "primary_skill", "alternatives",
                                      "clarification_recommended")},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
