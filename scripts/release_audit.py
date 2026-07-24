#!/usr/bin/env python3
"""Audit repository and package artifacts for release-blocking private data."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from personalization_audit import audit_repository  # noqa: E402


TEXT_SUFFIXES = {
    ".cfg", ".ini", ".json", ".jsonl", ".md", ".ps1", ".py", ".sh",
    ".toml", ".txt", ".yaml", ".yml",
}
PACKAGE_FORBIDDEN_NAMES = (
    ".intent-translator/",
    "profile.json",
    "language-observations.json",
    "memory.db",
    "student-state.db",
    "/backups/",
)


@dataclass(frozen=True)
class SecretRule:
    name: str
    pattern: re.Pattern[str]


# Keep detector fragments split so the scanner source does not contain a usable credential fixture.
SECRET_RULES = (
    SecretRule("private-key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    SecretRule("github-token", re.compile("gh" + r"[pousr]_[A-Za-z0-9]{20,}")),
    SecretRule("openai-key", re.compile("sk" + r"-[A-Za-z0-9_-]{20,}")),
    SecretRule("aws-access-key", re.compile("AK" + r"IA[0-9A-Z]{16}")),
    SecretRule(
        "literal-secret-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=]\s*"
            r"['\"][A-Za-z0-9_./+=-]{16,}['\"]"
        ),
    ),
)
_PLACEHOLDER_USER = r"(?!someone(?:[\\/])|example(?:[\\/])|user(?:[\\/])|username(?:[\\/]))"
PRIVATE_PATH = re.compile(
    rf"(?i)(?:[A-Z]:\\Users\\{_PLACEHOLDER_USER}[A-Za-z0-9._-]+\\[^\s\"'<>]+|"
    rf"/home/{_PLACEHOLDER_USER}[A-Za-z0-9._-]+/[^\s\"'<>]+|"
    rf"/Users/{_PLACEHOLDER_USER}[A-Za-z0-9._-]+/[^\s\"'<>]+)"
)


def repository_files(repo_root: Path) -> list[Path]:
    try:
        names: list[str] = []
        for command in (
            ["git", "ls-files", "-z"],
            ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        ):
            result = subprocess.run(command, cwd=repo_root, check=True, capture_output=True)
            names.extend(item for item in result.stdout.decode("utf-8").split("\0") if item)
        return [repo_root / item for item in dict.fromkeys(names)]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return [
            path
            for path in repo_root.rglob("*")
            if path.is_file() and not any(part in {".git", ".venv", "work", "dist", "build"} for part in path.parts)
        ]


def _scan_text(text: str, *, file_name: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in SECRET_RULES:
            if rule.pattern.search(line):
                findings.append({"file": file_name, "line": line_number, "rule": rule.name})
        if PRIVATE_PATH.search(line):
            findings.append({"file": file_name, "line": line_number, "rule": "private-home-path"})
    return findings


def audit_tree(repo_root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned = 0
    forbidden_files: list[str] = []
    for path in repository_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        lowered = relative.casefold()
        if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"} or any(
            marker in lowered for marker in ("/.intent-translator/", "/backups/")
        ):
            forbidden_files.append(relative)
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        scanned += 1
        findings.extend(_scan_text(text, file_name=relative))
    for relative in forbidden_files:
        findings.append({"file": relative, "line": None, "rule": "local-state-file"})
    return {"scanned_text_files": scanned, "findings": findings}


def _artifact_members(path: Path) -> Iterable[tuple[str, bytes]]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield name, archive.read(name)
        return
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is not None:
                        yield member.name, stream.read()


def audit_artifacts(paths: Iterable[Path]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    inspected: list[str] = []
    for path in paths:
        inspected.append(path.name)
        for member_name, payload in _artifact_members(path):
            normalized = "/" + member_name.replace("\\", "/").casefold()
            if any(marker.casefold() in normalized for marker in PACKAGE_FORBIDDEN_NAMES):
                findings.append({"artifact": path.name, "member": member_name, "rule": "private-package-member"})
            if Path(member_name).suffix.casefold() not in TEXT_SUFFIXES:
                continue
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeError:
                continue
            findings.extend(
                {"artifact": path.name, "member": member_name, **item}
                for item in _scan_text(text, file_name=member_name)
            )
    return {"inspected_artifacts": inspected, "findings": findings}


def run_audit(repo_root: Path, *, dist: Path | None = None, private_terms: list[str] | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    personalization = audit_repository(repo_root, private_terms=private_terms or [])
    tree = audit_tree(repo_root)
    artifact_paths = [] if dist is None or not dist.exists() else sorted(
        path for path in dist.iterdir() if path.suffix == ".whl" or path.name.endswith((".tar.gz", ".tgz", ".zip"))
    )
    artifacts = audit_artifacts(artifact_paths)
    total_findings = (
        len(personalization["findings"]) + len(tree["findings"]) + len(artifacts["findings"])
    )
    return {
        "schema_version": 1,
        "passed": total_findings == 0,
        "creator_shadow_leakage": personalization["creator_shadow_leakage"],
        "default_user_contamination_rate": personalization["default_user_contamination_rate"],
        "secret_or_private_path_findings": tree["findings"],
        "package_findings": artifacts["findings"],
        "scanned_text_files": tree["scanned_text_files"],
        "inspected_artifacts": artifacts["inspected_artifacts"],
        "total_findings": total_findings,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--private-term", action="append", default=[])
    args = parser.parse_args()
    report = run_audit(args.repo, dist=args.dist, private_terms=args.private_term)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
