"""Hashes for Skill-side runtime helpers executed by the packaged MCP server."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_SKILL_SCRIPT_HASHES = {
    "decision_receipt.py": "68549965c498e556886c495c25db5c9b8c91b85658a5d6132c4a980bfaa482a0",
    "discover_skills.py": "6e10545527db9e5e740f0e7a2ebdb99bdaf3f4f307a64ce5cb8cd8b7728369ba",
    "memory_store.py": "3675b929e5acad6003d93e4afc1de274ee01d1d04d9a3942b2469871d2dda1e9",
    "privacy_guard.py": "341fc67ebc34c79313a1942b4935aa955c9b0f96a9b5d7fa8229f47c87fb2664",
    "semantic_search.py": "0b2c032efea92917d6fd6cf93cc6b228c8686287d24e589d25ff24384cbd7a09",
}

DEPENDENCIES = {
    "memory_store.py": ("semantic_search.py",),
}


def verify_skill_script(script: Path) -> None:
    expected = EXPECTED_SKILL_SCRIPT_HASHES.get(script.name)
    if expected is None:
        raise RuntimeError(f"unrecognized runtime Skill script: {script.name}")
    actual = hashlib.sha256(script.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"runtime Skill script integrity mismatch: {script.name}; reinstall matching package and Skill versions"
        )
    for dependency in DEPENDENCIES.get(script.name, ()):
        verify_skill_script(script.with_name(dependency))
