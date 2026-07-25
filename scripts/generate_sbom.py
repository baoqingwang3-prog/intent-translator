#!/usr/bin/env python3
"""Generate a deterministic CycloneDX SBOM from an installed Python environment."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


DISCOVERY_CODE = r"""
import importlib.metadata as metadata
import json

rows = []
for dist in metadata.distributions():
    name = dist.metadata.get("Name")
    version = dist.version
    if not name or not version or name.casefold() in {"pip", "setuptools", "wheel"}:
        continue
    rows.append({
        "name": name,
        "version": version,
        "license": dist.metadata.get("License", ""),
        "requires": list(dist.requires or []),
    })
print(json.dumps(rows, ensure_ascii=False))
"""


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def discover(python: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [python, "-c", DISCOVERY_CODE],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = json.loads(completed.stdout)
    return sorted(rows, key=lambda item: normalized_name(item["name"]))


def build_sbom(rows: list[dict[str, Any]], *, root_name: str) -> dict[str, Any]:
    by_name = {normalized_name(item["name"]): item for item in rows}
    root = by_name.get(normalized_name(root_name))
    if root is None:
        raise ValueError(f"installed package not found for SBOM root: {root_name}")
    components = []
    dependencies = []
    for item in rows:
        name = normalized_name(item["name"])
        reference = f"pkg:pypi/{name}@{item['version']}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": reference,
            "name": item["name"],
            "version": item["version"],
            "purl": reference,
        }
        if str(item.get("license", "")).strip():
            component["licenses"] = [{"license": {"name": str(item["license"]).strip()}}]
        components.append(component)
        dependency_refs = []
        for requirement in item.get("requires", []):
            match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
            if not match:
                continue
            dependency = by_name.get(normalized_name(match.group(1)))
            if dependency:
                dependency_refs.append(
                    f"pkg:pypi/{normalized_name(dependency['name'])}@{dependency['version']}"
                )
        dependencies.append({"ref": reference, "dependsOn": sorted(set(dependency_refs))})
    fingerprint = "|".join(f"{item['name']}=={item['version']}" for item in rows)
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"intent-translator-sbom:{fingerprint}")
    root_ref = f"pkg:pypi/{normalized_name(root['name'])}@{root['version']}"
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": root["name"],
                "version": root["version"],
                "purl": root_ref,
            }
        },
        "components": components,
        "dependencies": dependencies,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--root-package", default="intent-translator-mcp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sbom = build_sbom(discover(args.python), root_name=args.root_package)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "components": len(sbom["components"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
