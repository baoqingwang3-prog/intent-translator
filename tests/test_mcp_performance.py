import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]


class McpPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_warm_roundtrip_and_default_payload_budgets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = dict(os.environ)
            env.update(
                {
                    "PYTHONPATH": str(REPO_ROOT / "src"),
                    "INTENT_TRANSLATOR_SKILL_DIR": str(
                        REPO_ROOT / "skills" / "intent-translator"
                    ),
                    "INTENT_TRANSLATOR_PROFILE": str(root / "profile.json"),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                }
            )
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "intent_translator_mcp.server"],
                env=env,
            )
            payload = {
                "request": {
                    "utterance": "Review the local project architecture",
                    "semantic_mode": "off",
                    "include_prompt": False,
                }
            }
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.call_tool("intent_compile", payload)
                    timings = []
                    result = None
                    for _ in range(10):
                        started = time.perf_counter()
                        result = await session.call_tool("intent_compile", payload)
                        timings.append((time.perf_counter() - started) * 1000)

            timings.sort()
            self.assertIsNotNone(result)
            serialized = json.dumps(result.structuredContent, ensure_ascii=False)
            self.assertLessEqual(len(serialized), 3500)
            self.assertLessEqual(timings[9], 150.0)
            self.assertFalse((root / "memory.db").exists())


if __name__ == "__main__":
    unittest.main()
