import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from privacy_guard import inspect_text, scan_text  # noqa: E402


class PrivacyGuardTests(unittest.TestCase):
    def test_clean_text_is_safe(self):
        result = inspect_text("Research local-first memory architectures.")
        self.assertTrue(result["safe_to_send"])
        self.assertEqual(result["finding_count"], 0)

    def test_detects_and_redacts_secret_and_identifiers_without_echoing_them(self):
        fake_token = "sk-" + "A" * 24
        text = f"token={fake_token}; contact me@example.com or 13800138000"
        result = inspect_text(text, include_redacted=True)
        categories = {item["category"] for item in result["findings"]}
        self.assertIn("openai_token", categories)
        self.assertIn("email", categories)
        self.assertIn("cn_phone", categories)
        self.assertNotIn(fake_token, result["redacted_text"])
        self.assertNotIn("me@example.com", result["redacted_text"])
        self.assertTrue(result["redacted_safe_to_send"])

    def test_scan_reports_masked_examples(self):
        fake_github_token = "ghp_" + "B" * 32
        findings = scan_text(fake_github_token)
        self.assertEqual(findings[0]["category"], "github_token")
        self.assertNotEqual(findings[0]["example"], fake_github_token)


if __name__ == "__main__":
    unittest.main()
