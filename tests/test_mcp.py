from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class McpSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_tools_are_read_only_and_limits_work_without_database(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "graphkoda_neo4j_mcp.server"],
            env=env,
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertEqual(
                    names,
                    {"get_limits", "check_connection", "inspect_neighborhood", "find_paths", "inspect_runtime_overlay"},
                )
                self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools.tools))
                result = await session.call_tool("get_limits", {})
                self.assertFalse(result.isError)
                self.assertFalse(result.structuredContent["arbitraryCypherEnabled"])


if __name__ == "__main__":
    unittest.main()
