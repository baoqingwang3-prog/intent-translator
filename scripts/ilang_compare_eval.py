"""Reproducible embedding, keyword and actual cascade comparison.

Run each model in a fresh process. --output saves predictions, hashes,
versions, coverage, and duplicate/anchor-overlap sensitivity views.
This historical evaluation is a development set, not a held-out test.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
# An explicit dependency override is allowed; installed venv dependencies win.
if os.environ.get("ILANG_DISTILL_DEPS"):
    sys.path.append(os.environ["ILANG_DISTILL_DEPS"])
sys.path.insert(0, str(ROOT / "src"))

import ilang_distill_router as router  # noqa: E402
import ilang_semantic_main as semantic_main  # noqa: E402
import intent_translator_mcp.core as core  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402

ROUTERS = ("embed", "embed_argmax", "keyword", "embed_first", "cascade")


def load_eval() -> list[dict]:
    with (HERE / "ilang_eval_set.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def metrics(rows: list[dict], name: str) -> dict:
    total = len(rows)
    hits = sum(row["predictions"][name] == row["expected_mode"] for row in rows)
    abstain = sum(row["predictions"][name] is None for row in rows)
    decided = total - abstain
    return {
        "total": total, "hit": hits, "miss": decided - hits, "abstain": abstain,
        "accuracy": hits / total if total else 0.0,
        "coverage": decided / total if total else 0.0,
        "selective_accuracy": hits / decided if decided else 0.0,
    }


def views(rows: list[dict]) -> dict:
    unique = list({row["utterance"]: row for row in rows}.values())
    subsets = {
        "all": rows,
        "unique": unique,
        "unique_without_anchor_overlap": [r for r in unique if not r["anchor_overlap"]],
    }
    for source in sorted({row["source"] for row in rows}):
        subsets["source:" + source] = [r for r in rows if r["source"] == source]
    return {key: {name: metrics(subset, name) for name in ROUTERS}
            for key, subset in subsets.items()}


def provenance() -> dict:
    model_name = os.environ.get("ILANG_DISTILL_EMBED_MODEL", router.DEFAULT_MODEL)
    core_file = Path(core.__file__).resolve()
    repository_root = ROOT.resolve()
    core_import_ref = (str(core_file.relative_to(repository_root))
                       if core_file.is_relative_to(repository_root) else "outside-repository")
    files = [HERE / name for name in (
        "ilang_compare_eval.py", "ilang_distill_router.py", "ilang_semantic_main.py",
        "ilang_semantic_adapter.py", "ilang_eval_set.jsonl", "ilang_distill_intents.json",
    )]
    files += sorted((ROOT / "src" / "intent_translator_mcp").glob("*.py"))
    packages = {name: importlib.metadata.version(name) for name in
                ("fastembed", "onnxruntime", "pydantic", "huggingface-hub")}
    return {
        "python": platform.python_version(),
        "python_environment": "venv" if sys.prefix != sys.base_prefix else "system",
        "core_import_ref": core_import_ref, "packages": packages,
        "project_version": (ROOT / "VERSION").read_text().strip(),
        "model": model_name,
        "batch_size": 1 if model_name.lower().startswith("intfloat/multilingual-e5") else 256,
        "model_path_set": bool(os.environ.get("ILANG_DISTILL_MODEL_PATH")),
        "offline": os.environ.get("ILANG_DISTILL_OFFLINE") == "1",
        "scoring": os.environ.get("ILANG_DISTILL_SCORING", "maxsim"),
        "thresholds": router.THRESHOLDS,
        "profile": "generic; memory disabled; empty skill registry",
        "sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in files},
    }


def _run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = load_eval()
    # Exclude personal profiles, corrections and installed-Skill discovery.
    kw = core.IntentCompiler(
        entrypoint="eval", registry={"skills": [], "errors": []},
        profile={"language": "auto", "phrase_mappings": {}, "memory": {"adapter": "none"}},
        profile_exists=False,
    )
    semantic_main._KW_COMPILER = kw
    anchors = {text for spec in router._load_intents()["modes"].values()
               for text in spec["utterances"]}
    meta = provenance()
    print(json.dumps({"model": meta["model"], "cases": len(cases),
                      "python": meta["python"], "offline": meta["offline"]}), flush=True)
    started = time.perf_counter()
    if meta["scoring"] == "maxsim":
        router.get_utterance_vecs()
    else:
        router.get_centroids()
    initialization_seconds = time.perf_counter() - started
    print(f"model + anchors initialized in {initialization_seconds:.1f}s", flush=True)
    rows = []
    for index, case in enumerate(cases, 1):
        utt = case["utterance"]
        started = time.perf_counter()
        embedding = router.route(utt)
        embed_seconds = time.perf_counter() - started
        started = time.perf_counter()
        keyword = kw.compile(CompileRequest(utterance=utt, semantic_mode="off"))
        keyword_seconds = time.perf_counter() - started
        started = time.perf_counter()
        # Execute production arbitration; do not duplicate its rules here.
        mode, decider, confidence = semantic_main.cascade_mode(utt)
        cascade_seconds = time.perf_counter() - started
        predictions = {
            "embed": embedding["mode"],
            "embed_argmax": next(iter(embedding["scores"]), None),
            "keyword": keyword.get("mode"),
            "embed_first": embedding["mode"] or keyword.get("mode"),
            "cascade": mode,
        }
        rows.append({
            **case, "anchor_overlap": utt in anchors, "predictions": predictions,
            "embedding": embedding, "keyword_confidence": keyword.get("confidence"),
            "cascade_decider": decider, "cascade_confidence": confidence,
            "seconds": {"embed": embed_seconds, "keyword": keyword_seconds,
                        "cascade": cascade_seconds},
        })
        if index % 20 == 0 or index == len(cases):
            print(f"evaluated {index}/{len(cases)}", flush=True)
    report = {
        "provenance": meta, "initialization_seconds": initialization_seconds,
        "views": views(rows), "rows": rows,
        "data_quality": {
            "rows": len(rows), "unique_utterances": len({r["utterance"] for r in rows}),
            "anchor_overlap_rows": sum(r["anchor_overlap"] for r in rows),
            "sources": dict(Counter(r["source"] for r in rows)),
            "limitation": "Development evaluation with repeats and anchor overlaps; no held-out claim.",
        },
        "timing_note": "Initialization separate; cascade re-encodes each query; CPU threads=1; batch size recorded in provenance.",
    }
    print(f"{'router':14s} {'hit':>5s} {'miss':>5s} {'abst':>5s} {'acc%':>7s} {'coverage%':>10s}")
    for name, result in report["views"]["all"].items():
        print(f"{name:14s} {result['hit']:5d} {result['miss']:5d} {result['abstain']:5d} "
              f"{result['accuracy'] * 100:6.1f}% {result['coverage'] * 100:9.1f}%")
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"report saved: {args.output}")


def main() -> None:
    key = "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON"
    previous = os.environ.get(key)
    os.environ[key] = "[]"
    try:
        _run()
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


if __name__ == "__main__":
    main()

