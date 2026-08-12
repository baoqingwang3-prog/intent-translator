"""Hashes for Skill-side runtime helpers executed by the packaged MCP server."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_SKILL_SCRIPT_HASHES = {
    "decision_receipt.py": "68549965c498e556886c495c25db5c9b8c91b85658a5d6132c4a980bfaa482a0",
    "discover_skills.py": "8f06c979086bf26b635973482c7daaaa096b988385e46a2c5d6003bc2d9bbd19",
    "memory_store.py": "2d92dc6851328bc0765be7e6f32bd34f8d0af12bb14a570a6770374960efb5ee",
    "skill_registry.py": "71a080727fb52fa97bbf5b592f545977f10ed0d81f78c6a83bb146fd0eedbeb3",
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
