r"""I-Lang semantic adapter for intent-translator.

Reads one JSON payload on stdin (the semantic_payload shape produced by
intent_translator_mcp.semantic), parses I-Lang syntax from the "utterance"
field, and emits one SemanticProposal JSON object on stdout.

I-Lang syntax handled:
    [VERB:@TARGET|mod=val]=>[VERB2]=>[OUT]      operations chain
    ::GENE{...}                                  declarations (behavior DNA)
    Greek symbol aliases: Σ Δ φ ∇ λ ∂ μ ψ ξ ζ θ Ω Π

Mapping rules (I-Lang verb -> intent-translator mode):
    READ GET LIST SCAN STRM CACH SYNC           -> answer / search
    FMT CONV XLAT θ REWR PARA STYL              -> change
    CREA DRFT GEN TMPL FILL EXPD                -> build
    SHRT ζ CMPR REDU CHNK                       -> compress
    remember / memory verbs (MEM, CACH-write)   -> remember
    RECAL RECALL                                -> recall
    ROUTE LINK                                  -> route
    DIAG ANOM EVAL AUDT CHEK FIX                -> diagnose
    everything else                             -> change (conservative default)

Risk hints: WRIT DEL SEND DPLO MOVE and external entities
    (@GH @R2 @COS @DRIVE @WORKER @CF) map to RISK_HINTS values.

Pure stdlib, no network. Local-only adapter (external=False).
"""

from __future__ import annotations

import json
import re
import sys

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VALID_MODES = {
    "answer", "diagnose", "change", "build", "search", "learn",
    "remember", "recall", "compress", "route",
}
VALID_RISKS = {"external", "sensitive", "irreversible", "high_stakes"}

GREEK_ALIASES = {
    "Σ": "MERGE", "Δ": "DIFF", "φ": "FILT", "∇": "SORT", "λ": "MAP",
    "∂": "SPLIT", "μ": "STAT", "ψ": "SENT", "ξ": "HASH", "ζ": "CMPR",
    "θ": "XLAT", "Ω": "OUT", "Π": "BATC",
}

MODE_BY_VERB = {
    # data I/O
    "READ": "answer", "GET": "search", "LIST": "search", "SCAN": "search",
    "STRM": "answer", "CACH": "remember", "SYNC": "change",
    # transform
    "FMT": "change", "CONV": "change", "SPLIT": "change", "MERGE": "change",
    "MAP": "change", "FILT": "change", "SORT": "change", "DEDU": "change",
    "FLAT": "change", "NEST": "change", "CHNK": "compress", "REDU": "compress",
    "PIVT": "change", "TRNS": "change", "ENCD": "change", "DECD": "change",
    "HASH": "change", "CMPR": "compress", "EXPN": "build", "XLAT": "change",
    "REWR": "change", "DIFF": "diagnose",
    # analysis
    "MTCH": "search", "CNT": "answer", "STAT": "answer", "EVAL": "diagnose",
    "SCOR": "answer", "RANK": "search", "TRND": "answer", "CORR": "diagnose",
    "FRCS": "answer", "ANOM": "diagnose", "SENT": "answer", "CLST": "search",
    "BNCH": "diagnose", "AUDT": "diagnose", "VALD": "diagnose", "CLSF": "search",
    # generation
    "CREA": "build", "DRFT": "build", "SHRT": "compress", "PARA": "change",
    "STYL": "change", "TMPL": "build", "FILL": "build", "EXTC": "answer",
    "GEN": "build",
    # execution
    "PLAN": "route", "DECI": "route", "CHEK": "diagnose", "FIX": "diagnose",
    "DPLO": "change", "SAVE": "change", "REVW": "diagnose", "LERN": "learn",
    "TEST": "diagnose", "PARS": "answer", "LOOP": "change", "WAIT": "route",
    # output
    "OUT": "answer", "DISP": "answer", "EXPT": "change", "PRNT": "answer",
    "LOG": "remember",
    # structure / meta
    "LINK": "route", "SET": "change", "TAG": "remember", "GRP": "change",
    "EMBD": "change",
    "HELP": "answer", "DESC": "answer", "INTR": "answer", "NOOP": "route",
    "BATC": "change",
    # memory-ish extensions
    "MEM": "remember", "RECALL": "recall", "REMEM": "remember",
    "ROUTE": "route", "DIAG": "diagnose",
}

WRITE_VERBS = {"WRIT", "DEL", "SEND", "MOVE", "DPLO", "SAVE", "EXPT", "COPY"}
EXTERNAL_ENTITIES = {"@GH", "@R2", "@COS", "@DRIVE", "@WORKER", "@CF"}

STEP_RE = re.compile(r"\[([A-Za-zΩΣΔφ∇λ∂μψξζθΠ]*)\s*(?::\s*([^\]|]*)\s*)?(?:\|([^\]]*))?\]")
DECL_RE = re.compile(r"::[A-Z]+\{[^}]*\}")


def parse_steps(text: str) -> list[dict]:
    steps = []
    for match in STEP_RE.finditer(text):
        verb_raw, target, mods_raw = match.groups()
        if not verb_raw:
            continue
        verb = GREEK_ALIASES.get(verb_raw, verb_raw.upper())
        mods = {}
        if mods_raw:
            for pair in mods_raw.split(","):
                if "=" in pair:
                    key, _, value = pair.partition("=")
                    mods[key.strip()] = value.strip()
        steps.append({"verb": verb, "target": (target or "").strip(), "mods": mods})
    return steps


def build_proposal(payload: dict) -> dict:
    utterance = str(payload.get("utterance", "")).strip()
    deterministic = payload.get("deterministic_draft") or {}
    steps = parse_steps(utterance)

    if not steps:
        # Not I-Lang; hand back a low-confidence pass-through so the
        # deterministic compiler stays authoritative.
        return {
            "normalized_goal": str(deterministic.get("normalized_goal") or utterance)[:1000],
            "interpretation": "No I-Lang steps detected; deferring to deterministic draft.",
            "mode": None,
            "assumptions": [],
            "alternatives": [],
            "confidence": 0.2,
            "primary_skill": None,
            "risk_hints": [],
            "clarification_recommended": False,
            "language": "zh",
        }

    verbs = [step["verb"] for step in steps]
    modes = [MODE_BY_VERB.get(v) for v in verbs if MODE_BY_VERB.get(v)]
    mode = modes[0] if modes else "change"
    if mode not in VALID_MODES:
        mode = "change"

    # Last meaningful target wins; fall back to modifiers.
    target = next((s["target"] for s in reversed(steps) if s["target"]), "")
    path = next(
        (s["mods"].get("path") for s in steps if s.get("mods", {}).get("path")),
        "",
    )
    lang = next(
        (s["mods"].get("lng") for s in steps if s.get("mods", {}).get("lng")),
        "",
    )
    style = next(
        (s["mods"].get("sty") for s in steps if s.get("mods", {}).get("sty")),
        "",
    )
    fmt = next(
        (s["mods"].get("fmt") for s in steps if s.get("mods", {}).get("fmt")),
        "",
    )

    risk_hints = []
    if any(v in WRITE_VERBS for v in verbs):
        risk_hints.append("irreversible" if "DEL" in verbs else "external")
    if any(step["target"].upper() in EXTERNAL_ENTITIES for step in steps):
        if "external" not in risk_hints:
            risk_hints.append("external")
    risk_hints = [r for r in risk_hints if r in VALID_RISKS][:4]

    verb_chain = " -> ".join(verbs)
    parts = [f"I-Lang chain: {verb_chain}."]
    if target:
        parts.append(f"target {target}.")
    if path:
        parts.append(f"path {path}.")
    if style:
        parts.append(f"style {style}.")
    if fmt:
        parts.append(f"format {fmt}.")
    interpretation = " ".join(parts)[:1500]

    assumptions = []
    if target.startswith("@"):
        assumptions.append(f"entity {target} refers to local-available source")

    return {
        "normalized_goal": interpretation.rstrip(".")[:1000],
        "interpretation": interpretation,
        "mode": mode,
        "assumptions": assumptions[:8],
        "alternatives": [],
        "confidence": 0.85,
        "primary_skill": None,
        "risk_hints": risk_hints,
        "clarification_recommended": "OUT" not in verbs,
        "language": lang or "zh",
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 1
    proposal = build_proposal(payload)
    json.dump(proposal, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
