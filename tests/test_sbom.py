import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_sbom import build_sbom  # noqa: E402


class SbomTests(unittest.TestCase):
    def test_sbom_is_stable_and_links_installed_dependencies(self):
        rows = [
            {"name": "intent-translator-mcp", "version": "1.0.0", "license": "MIT", "requires": ["mcp>=1"]},
            {"name": "mcp", "version": "1.2.3", "license": "MIT", "requires": ["pydantic>=2"]},
            {"name": "pydantic", "version": "2.0.0", "license": "MIT", "requires": []},
        ]
        first = build_sbom(rows, root_name="intent-translator-mcp")
        second = build_sbom(rows, root_name="intent-translator-mcp")
        self.assertEqual(first, second)
        self.assertEqual(first["bomFormat"], "CycloneDX")
        self.assertEqual(first["metadata"]["component"]["version"], "1.0.0")
        root_dependency = next(
            item for item in first["dependencies"] if "intent-translator-mcp" in item["ref"]
        )
        self.assertEqual(root_dependency["dependsOn"], ["pkg:pypi/mcp@1.2.3"])


if __name__ == "__main__":
    unittest.main()
