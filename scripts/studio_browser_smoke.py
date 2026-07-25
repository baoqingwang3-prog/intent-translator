#!/usr/bin/env python3
"""Run the local Studio through real browser viewports in a clean room."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from intent_translator_mcp import __version__  # noqa: E402
from intent_translator_mcp.studio import create_server  # noqa: E402


def build_smoke_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "viewports": [
            {"name": "desktop", "width": 1440, "height": 900},
            {"name": "mobile", "width": 390, "height": 844},
        ],
        "scenarios": [
            {
                "id": "continue",
                "may_execute": True,
                "understanding_includes": ["继续完善本地测试", "不上传 GitHub"],
                "source_map_includes": ["禁止动作"],
            },
            {
                "id": "negative",
                "may_execute": False,
                "understanding_includes": ["不要发布"],
            },
            {
                "id": "route",
                "may_execute": True,
                "selected_skill": "agent-reach",
            },
            {
                "id": "correction",
                "may_execute": True,
                "requires_comparison": True,
            },
        ],
        "required_public_terms": [],
        "result_replaces_empty_state": True,
        "generic_first_run_label": "通用模式 · 无个人记忆",
        "forbidden_first_view_terms": ["ExecutionEnvelope", "SQLite", "adapter", "MCP"],
    }


@contextmanager
def temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def write_synthetic_skills(root: Path) -> None:
    skills = {
        "agent-reach": (
            "Search and research GitHub and the public internet. Own search, lookup, and retrieval actions."
        ),
        "skill-creator": "Create or revise an Agent Skill from a natural-language capability request.",
    }
    for name, description in skills.items():
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )


def resolve_executable(explicit: str, env_name: str, fallback: str) -> str:
    candidate = explicit or os.environ.get(env_name, "") or shutil.which(fallback) or ""
    if not candidate or not Path(candidate).exists():
        raise RuntimeError(f"{fallback} executable not found; pass --{fallback}")
    return str(Path(candidate).resolve())


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    node = resolve_executable(args.node, "INTENT_TRANSLATOR_NODE", "node")
    node_modules = args.node_modules or os.environ.get("INTENT_TRANSLATOR_NODE_MODULES", "")
    if not node_modules:
        node_modules = os.environ.get("NODE_PATH", "")
    if not node_modules:
        raise RuntimeError("Playwright module path not found; pass --node-modules")

    output = Path(args.output).resolve() if args.output else None
    screenshot_dir = Path(args.screenshot_dir).resolve() if args.screenshot_dir else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="intent-studio-browser-") as temp:
        clean_root = Path(temp)
        skill_root = clean_root / "skills"
        write_synthetic_skills(skill_root)
        env_values = {
            "HOME": str(clean_root),
            "USERPROFILE": str(clean_root),
            "APPDATA": str(clean_root / "appdata" / "roaming"),
            "LOCALAPPDATA": str(clean_root / "appdata" / "local"),
            "XDG_CONFIG_HOME": str(clean_root / "config"),
            "CODEX_HOME": str(clean_root / "codex"),
            "CLAUDE_CONFIG_DIR": str(clean_root / "claude"),
            "INTENT_TRANSLATOR_PROFILE": str(clean_root / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(clean_root / "memory.db"),
            "INTENT_TRANSLATOR_SKILL_ROOTS": str(skill_root),
            "INTENT_TRANSLATOR_SEMANTIC_MODE": "off",
            "PYTHONUTF8": "1",
        }
        with temporary_environment(env_values):
            server = create_server("127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                child_env = dict(os.environ)
                child_env.update(
                    {
                        "NODE_PATH": str(Path(node_modules).resolve()),
                        "STUDIO_URL": f"http://127.0.0.1:{server.server_address[1]}",
                        "STUDIO_SMOKE_CONTRACT": json.dumps(build_smoke_contract(), ensure_ascii=False),
                        "STUDIO_SCREENSHOT_DIR": str(screenshot_dir or ""),
                        "STUDIO_BROWSER_EXECUTABLE": args.browser_executable,
                    }
                )
                completed = subprocess.run(
                    [node, str(REPO_ROOT / "scripts" / "studio_browser_smoke.cjs")],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=child_env,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    if completed.returncode != 0:
        raise RuntimeError((completed.stdout + completed.stderr).strip())
    report = json.loads(completed.stdout)
    report.update(
        {
            "package_version": __version__,
            "clean_room": True,
            "creator_profile_loaded": False,
            "git_publish_performed": False,
        }
    )
    if output:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="")
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--browser-executable", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--screenshot-dir", default="")
    args = parser.parse_args()
    try:
        report = run_smoke(args)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema_version": 1, "passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
