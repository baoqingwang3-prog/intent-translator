r"""Natural language -> I-Lang compiler (reverse of the syntax adapter).

Pipeline (signals layered, cheapest first):
1. embedding router picks the intent mode (reuse ilang_distill_router)
2. mode -> I-Lang verb-chain template
3. regex slot extraction fills modifiers: len / lng / sty / fmt / path / whr
4. emit a compilable I-Lang statement

Usage:
    echo {"utterance": "..."} | python ilang_nl2ilang.py
    -> {"ilang": "[READ:@SRC]=>[EXTC]=>[SHRT|len=3]=>[OUT]", ...}

This is a template expander, not a mind: it always emits runnable syntax,
and marks low-confidence output so the caller can double-check.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# mode -> I-Lang chain template. {mods} is filled by slot extraction.
MODE_TO_ILANG: dict[str, str] = {
    "answer":   "[READ:@SRC{path}]=>[EXTC{whr}]=>[SHRT|sty=bullets{len}]=>[OUT]",
    "search":   "[SCAN:@GH{whr}]=>[RANK]=>[SHRT|len=5]=>[OUT]",
    "build":    "[CREA:@DST{path}]=>[TEST]=>[OUT]",
    "change":   "[READ:@SRC{path}]=>[REWR{mods}]=>[SAVE]=>[OUT]",
    "diagnose": "[READ:@LOG]=>[SCAN{whr}]=>[DIAG]=>[OUT]",
    "learn":    "[EXPD:@SRC]=>[PARA|sty=examples]=>[OUT]",
    "remember": "[WRIT:@LOCAL{path}]=>[TAG]=>[OUT]",
    "recall":   "[RECALL:@LOCAL]=>[FILT{whr}]=>[OUT]",
    "compress": "[READ:@SRC]=>[CMPR|sty=bullets{len}]=>[OUT]",
    "route":    "[PLAN:@PREV]=>[LINK]=>[OUT]",
}

TRANSLATE_RE = re.compile(r"翻[译譯]|译[成到]|转[成译]")

NUM_WORDS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

LANG_WORDS = {
    "英文": "en", "英语": "en", "中文": "zh", "日文": "ja", "日语": "ja",
}

LANG_HINT_RE = re.compile(r"(翻[译成]|译成|翻译[成到]|转成英文|转成中文)")
TARGET_LANG_RE = re.compile(r"(?:翻译|译|转)[^，。;；]*?(?:成|到|为)?(英文|英语|中文|日文|日语)")


def extract_len(text: str) -> str:
    m = re.search(r"(\d+)\s*(条|个|点|句|行)", text)
    if m:
        return m.group(1)
    m = re.search(r"([一两二三四五六七八九十])\s*(条|个|点|句|行)", text)
    if m:
        return str(NUM_WORDS.get(m.group(1), ""))
    if re.search(r"简短|简略|精简|一句话", text):
        return "3"
    return ""


def extract_lang(text: str) -> str:
    m = TARGET_LANG_RE.search(text)
    if m:
        return LANG_WORDS.get(m.group(1), "")
    return ""


def extract_style(text: str) -> str:
    if re.search(r"列表|要点|条目|bullet", text):
        return "bullets"
    if re.search(r"表格|table", text):
        return "table"
    if re.search(r"段落|成段", text):
        return "paragraph"
    return "bullets"


def extract_fmt(text: str) -> str:
    if re.search(r"markdown|md\b|\.md", text, re.I):
        return "md"
    if re.search(r"json", text, re.I):
        return "json"
    if re.search(r"csv", text, re.I):
        return "csv"
    return ""


def extract_path(text: str) -> str:
    m = re.search(r"([\w\-./\\]+\.(?:md|txt|json|csv|py|js|ts|html|yaml|yml))", text)
    if m:
        return m.group(1).replace("\\", "/")
    return ""


def extract_whr(text: str) -> str:
    m = re.search(r"(?:关于|有关|包含|含|涉及)([\w\u4e00-\u9fff]{2,12})", text)
    if m:
        return m.group(1)
    return ""


def compile_ilang(utterance: str) -> dict:
    from ilang_distill_router import route

    result = route(utterance)
    mode = result["mode"]
    if not mode:
        return {
            "ilang": "",
            "mode": None,
            "confidence": result["confidence"],
            "note": "router abstained; rephrase or write I-Lang directly",
        }

    slots = {
        "len": extract_len(utterance),
        "lng": extract_lang(utterance),
        "sty": extract_style(utterance),
        "fmt": extract_fmt(utterance),
        "path": extract_path(utterance),
        "whr": extract_whr(utterance),
    }

    def mod_str(*keys: str) -> str:
        pairs = [f"{k}={slots[k]}" for k in keys if slots.get(k)]
        return "|" + ",".join(pairs) if pairs else ""

    chain = MODE_TO_ILANG[mode]
    if TRANSLATE_RE.search(utterance) and slots.get("lng"):
        path_mod = f"|path={slots['path']}" if slots["path"] else ""
        chain = f"[READ:@SRC{path_mod}]=>[XLAT|lng={slots['lng']},ton=formal]=>[OUT]"

    chain = (
        chain.replace("{path}", mod_str("path") if "{path}" in chain else "")
        .replace("{whr}", mod_str("whr"))
        .replace("{len}", mod_str("len"))
        .replace("{mods}", mod_str("sty", "fmt", "lng"))
    )
    chain = re.sub(r"\|([a-z]+=\w+)\|\1", r"|\1", chain)  # collapse dupes
    chain = re.sub(r"\|([a-z]+=[^,\]]+),\1=[^,\]]+", r"|\1", chain)

    return {
        "ilang": chain,
        "mode": mode,
        "confidence": result["confidence"],
        "slots": {k: v for k, v in slots.items() if v},
        "note": "ok" if result["accepted"] else "weak match, verify chain",
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 1
    utterance = str(payload.get("utterance", "")).strip()
    if not utterance:
        return 1
    json.dump(compile_ilang(utterance), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
