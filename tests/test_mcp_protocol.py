import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_lists_and_calls_all_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env.update(
                {
                    "PYTHONPATH": str(REPO_ROOT / "src"),
                    "INTENT_TRANSLATOR_SKILL_DIR": str(
                        REPO_ROOT / "skills" / "intent-translator"
                    ),
                    "INTENT_TRANSLATOR_PROFILE": str(Path(temp) / "profile.json"),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(Path(temp) / "memory.db"),
                }
            )
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "intent_translator_mcp.server"],
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertEqual(
                        {tool.name for tool in listed.tools},
                        {
                            "intent_compile",
                            "intent_check",
                            "intent_recall_corrections",
                            "intent_record_correction",
                            "intent_suggest_correction",
                            "intent_confirm_correction",
                            "intent_record_outcome",
                        },
                    )
                    called = await session.call_tool(
                        "intent_compile",
                        {
                            "request": {
                                "utterance": "可以",
                                "context": "The agent proposed creating and validating a Skill.",
                            }
                        },
                    )
                    self.assertFalse(called.isError)
                    self.assertEqual(called.structuredContent["mode"], "build")
                    self.assertEqual(
                        called.structuredContent["routing"]["primary_skill"],
                        "skill-creator",
                    )
                    suggested = await session.call_tool(
                        "intent_suggest_correction",
                        {
                            "request": {
                                "message": "太复杂了",
                                "previous_behavior": "Used a long answer for a simple confirmation.",
                            }
                        },
                    )
                    self.assertFalse(suggested.isError)
                    self.assertTrue(suggested.structuredContent["ready_for_confirmation"])
                    confirmed = await session.call_tool(
                        "intent_confirm_correction",
                        {"request": {"pending_id": suggested.structuredContent["id"]}},
                    )
                    self.assertFalse(confirmed.isError)
                    self.assertEqual(confirmed.structuredContent["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
