r"""A/B: does the skill-candidates field in the semantic proposal change
the compiler's execute decision for H148? Wire the REAL subprocess adapter
and compile the same utterance with two proposal variants."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.append(str(Path.home() / ".workbuddy-ai" / "binaries" / "node" / "workspace" / "pydeps"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import adapter_from_env  # noqa: E402

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
    argv = [PY, "-B", str(MAIN)]
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


UTT = "查一下机票价格，不要帮我把钱付了"

for name, primary, alts in [
    ("clean", None, []),
    ("primary", "agent-reach", []),
    ("alts-only", None, ["agent-reach", "smart-search"]),
]:
    env = run(primary, alts)
    cc = env["completion_contract"]
    print(f"{variant if (variant := name) else name:10s} execute={cc['execute']} mode={env['mode']} "
          f"egress={env['intent_contract']['data_egress']} skill={env['routing']['primary_skill']}")

# show what the subprocess semantic proposal actually is for the same input
adapter = adapter_from_env({
    "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps([PY, "-B", MAIN]),
    "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "120",
})
with tempfile.TemporaryDirectory(prefix="ilang-ab2-") as temporary:
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
        proposal = adapter.run(CompileRequest(
            utterance=UTT, context="", pending_action="", semantic_mode="required"))
print("subprocess proposal:", json.dumps(
    {k: proposal.get(k) for k in ("mode", "confidence", "primary_skill", "alternatives",
                                  "clarification_recommended")},
    ensure_ascii=False))