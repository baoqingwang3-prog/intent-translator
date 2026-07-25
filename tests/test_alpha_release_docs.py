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


if __name__ == "__main__":
    unittest.main()
