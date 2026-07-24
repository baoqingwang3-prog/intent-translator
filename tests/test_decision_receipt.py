import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "intent-translator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from decision_receipt import assert_no_hidden_reasoning, build_receipt  # noqa: E402


class DecisionReceiptTests(unittest.TestCase):
    def test_builds_auditable_receipt_without_copying_internal_fields(self):
        receipt = build_receipt(
            {
                "normalized_goal": "继续当前安装验证",
                "mode": "change",
                "memories": [
                    {
                        "id": 7,
                        "text": "好了表示之前的阻塞已经解除",
                        "scope": "global",
                    }
                ],
                "routing": {"primary_skill": "intent-translator", "reason": "matched phrase mapping"},
                "risk": {"confirmation_required": False, "reasons": []},
                "analysis": "This must never be copied into the receipt.",
            }
        )
        self.assertEqual(receipt["understood_as"], "继续当前安装验证")
        self.assertEqual(receipt["used_memory"][0]["id"], 7)
        self.assertEqual(receipt["selected_skill"], "intent-translator")
        self.assertNotIn("analysis", receipt)
        assert_no_hidden_reasoning(receipt)

    def test_marks_conflicting_memory_and_confirmation(self):
        receipt = build_receipt(
            {
                "goal": "发布仓库",
                "memory_refs": [
                    {
                        "id": 9,
                        "summary": "简短同意不等于发布授权",
                        "governance": {"requires_clarification": True},
                    }
                ],
                "risk": {
                    "confirmation_required": True,
                    "reasons": ["external action lacks explicit authorization"],
                },
            }
        )
        self.assertTrue(receipt["used_memory"][0]["conflict"])
        self.assertTrue(receipt["confirmation_required"])
        self.assertIn("需要确认", receipt["summary"])


if __name__ == "__main__":
    unittest.main()
