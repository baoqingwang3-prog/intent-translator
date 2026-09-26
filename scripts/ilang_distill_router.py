r"""Embedding-based intent router distilled from GitHub prior art.

Distillation sources:
- aurelio-labs/semantic-router : Route + utterances as semantic anchors
- voml77/embedding-intent-router : centroid + dual-threshold accept/reject
- vllm-project/semantic-router : signals layered (cheap -> expensive)
- microsoft/TypeChat : typed schema repair prompt (falls back to adapter)

Design:
- 10 modes match intent_translator_mcp.semantic.MODES exactly.
- Each mode has ~12 zh/en prototype utterances stored in intents JSON.
- Query is embedded with a local multilingual ONNX model (fastembed),
  compared to per-mode centroids by cosine similarity.
- Dual threshold: strong accept, weak accept with margin, else abstain.
- Abstain -> confidence below 0.5, letting the deterministic compiler
  and (if configured) the I-Lang adapter stay authoritative.

This is a router, not a mind reader: it only proposes {mode, confidence,
scores}. Authorization and risk stay with the host compiler.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
INTENTS_PATH = HERE / "ilang_distill_intents.json"
# BGE-small-zh is the default: 100MB resident (fits the <=1GB budget),
# no external-data path issues. E5-large is opt-in via ILANG_DISTILL_EMBED_MODEL
# + ILANG_DISTILL_MODEL_PATH (assembled dir, see ilang_baseline_README.md).
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

THRESHOLDS = {
    "accept": 0.46,
    "weak_accept": 0.40,
    "min_margin": 0.04,
}

_MODEL_CACHE: dict[str, object] = {}


def _load_encoder():
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]
    deps = os.environ.get(
        "ILANG_DISTILL_DEPS",
        os.path.join(os.path.expanduser("~"), ".workbuddy-ai/binaries/node/workspace/pydeps"),
    )
    for p in (deps, str(HERE.parent.parent / "pydeps")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    from fastembed import TextEmbedding  # type: ignore

    model_name = os.environ.get(
        "ILANG_DISTILL_EMBED_MODEL", DEFAULT_MODEL
    )
    options = {"threads": 1}
    if os.environ.get("ILANG_DISTILL_MODEL_PATH"):
        options["specific_model_path"] = os.environ["ILANG_DISTILL_MODEL_PATH"]
    if os.environ.get("ILANG_DISTILL_OFFLINE") == "1":
        options["local_files_only"] = True
    model = TextEmbedding(model_name=model_name, **options)
    _MODEL_CACHE["model"] = model
    return model


def _embed(texts: list[str]) -> list[list[float]]:
    model = _load_encoder()
    # E5 classification compares symmetric inputs: both anchors and queries
    # require "query: ". Fastembed's pooled E5 encoder adds no prefix itself.
    if model.model_name.lower().startswith("intfloat/multilingual-e5"):
        texts = ["query: " + text for text in texts]
        # Bound E5 memory without changing the existing BGE batching behavior.
        vectors = model.embed(texts, batch_size=1)
    else:
        vectors = model.embed(texts)
    return [list(map(float, v)) for v in vectors]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _load_intents() -> dict:
    with open(INTENTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def build_centroids(intents: dict) -> dict[str, list[float]]:
    centroids: dict[str, list[float]] = {}
    for mode, spec in intents["modes"].items():
        examples = list(spec["utterances"])
        vecs = _embed(examples)
        dim = len(vecs[0])
        centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        centroids[mode] = centroid
    return centroids


_CENTROID_CACHE: dict[str, dict[str, list[float]]] = {}


def get_centroids() -> dict[str, list[float]]:
    key = str(INTENTS_PATH.stat().st_mtime_ns)
    if key not in _CENTROID_CACHE:
        _CENTROID_CACHE.clear()
        _CENTROID_CACHE[key] = build_centroids(_load_intents())
    return _CENTROID_CACHE[key]


_UTTERANCE_VECS_CACHE: dict[str, dict[str, list[list[float]]]] = {}


def get_utterance_vecs() -> dict[str, list[list[float]]]:
    """Per-mode utterance vectors for max-sim scoring (aurelio style)."""
    key = str(INTENTS_PATH.stat().st_mtime_ns)
    if key not in _UTTERANCE_VECS_CACHE:
        intents = _load_intents()
        vecs: dict[str, list[list[float]]] = {}
        for mode, spec in intents["modes"].items():
            vecs[mode] = _embed(list(spec["utterances"]))
        _UTTERANCE_VECS_CACHE.clear()
        _UTTERANCE_VECS_CACHE[key] = vecs
    return _UTTERANCE_VECS_CACHE[key]


def route(query: str) -> dict:
    intents = _load_intents()
    scoring = os.environ.get("ILANG_DISTILL_SCORING", "maxsim")
    qvec = _embed([query])[0]
    if scoring == "maxsim":
        utt_vecs = get_utterance_vecs()
        scores = {
            mode: max(_cosine(qvec, v) for v in vecs)
            for mode, vecs in utt_vecs.items()
        }
    else:
        centroids = get_centroids()
        scores = {mode: _cosine(qvec, vec) for mode, vec in centroids.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_mode, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best - second

    accepted = best >= THRESHOLDS["accept"] or (
        best >= THRESHOLDS["weak_accept"] and margin >= THRESHOLDS["min_margin"]
    )
    confidence = round(min(1.0, max(0.0, best)), 4)
    if not accepted:
        confidence = round(confidence * 0.5, 4)
    return {
        "mode": best_mode if accepted else None,
        "accepted": accepted,
        "confidence": confidence,
        "raw_score": round(best, 4),
        "margin": round(margin, 4),
        "scores": {m: round(s, 4) for m, s in ranked[:4]},
        "description": intents["modes"].get(best_mode, {}).get("description", ""),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 1
    utterance = str(payload.get("utterance", "")).strip()
    deterministic = payload.get("deterministic_draft") or {}
    if not utterance:
        return 1
    result = route(utterance)
    proposal = {
        "normalized_goal": str(deterministic.get("normalized_goal") or utterance)[:1000],
        "interpretation": (
            f"Embedding router (distilled): mode={result['mode'] or 'abstain'}, "
            f"score={result['raw_score']}, margin={result['margin']}."
        ),
        "mode": result["mode"],
        "assumptions": [],
        "alternatives": [
            m for m in result["scores"] if m != (result["mode"] or "")
        ][:3],
        "confidence": result["confidence"],
        "primary_skill": None,
        "risk_hints": [],
        "clarification_recommended": not result["accepted"],
        "language": "zh",
    }
    json.dump(proposal, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
