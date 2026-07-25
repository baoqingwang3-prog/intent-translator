import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class AlphaReleaseDocumentationTests(unittest.TestCase):
    def test_readme_exposes_alpha_value_studio_and_complementary_routing(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "Make the agent understand the request, preserve authorization boundaries, and choose the right Skill before it acts.",
            readme,
        )
        self.assertIn("intent-translator-studio", readme)
        self.assertIn("Agent Reach", readme)
        self.assertIn("docs/support-matrix.md", readme)

    def test_support_matrix_distinguishes_verified_and_unverified_hosts(self):
        matrix = (REPO_ROOT / "docs" / "support-matrix.md").read_text(encoding="utf-8")
        for label in ("Alpha-supported", "Experimental", "Skill-only", "MCP unverified"):
            self.assertIn(label, matrix)
        self.assertIn("Remote CI pending", matrix)
        self.assertIn("restart", matrix.casefold())

    def test_skill_listing_describes_the_full_control_layer(self):
        metadata = (
            REPO_ROOT / "skills" / "intent-translator" / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")
        for capability in ("understanding", "authorization", "memory", "routing"):
            self.assertIn(capability, metadata.casefold())

    def test_studio_console_entrypoint_is_packaged(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(
            'intent-translator-studio = "intent_translator_mcp.studio:main"',
            pyproject,
        )

    def test_browser_smoke_is_reproducible_and_ci_gated(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        release_gate = (REPO_ROOT / "docs" / "release-gate.md").read_text(encoding="utf-8")
        evidence_path = REPO_ROOT / "docs" / "evidence" / "studio-browser-smoke-0.7.0a2.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertIn("scripts/studio_browser_smoke.py", workflow)
        self.assertIn("playwright@1.61.1", workflow)
        self.assertIn("playwright install", workflow)
        self.assertIn("scripts/studio_browser_smoke.py", release_gate)
        self.assertIn("studio-browser-smoke-0.7.0a2.json", release_gate)
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["metrics"]["horizontal_overflow_count"], 0)
        self.assertEqual(evidence["metrics"]["unsafe_execution_count"], 0)


if __name__ == "__main__":
    unittest.main()
