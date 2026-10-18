"""Standalone MCP stdio client probe.

Per ARCHITECTURE.md Task B6:
- Spawns the MCP server as a stdio child process via python -m mcp_server.
- Lists all tools and verifies all 11 are registered.
- Calls each tool once with sample arguments from the live graph.
- Validates each response as ToolResult.
- Prints tool name, ok flag, and summary.
- Includes one deliberate unknown-id call that must return ok=False.
"""

import asyncio
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Ensure backend is on sys.path so brain_core models can be loaded
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from brain_core.models import ToolResult


async def run_probe() -> None:
    """Execute live MCP probe over stdio transport."""
    env = os.environ.copy()
    python_path = str(BACKEND_DIR)
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = python_path

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        env=env,
        cwd=str(BACKEND_DIR),
    )

    print("Connecting to MCP server via stdio transport...", flush=True)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_list_res = await session.list_tools()
            tools = tool_list_res.tools
            print(f"Server initialized. Discovered {len(tools)} tools.\n", flush=True)

            expected_tools = [
                ("search_knowledge", {"query": "error handling", "kinds": ["Doc"], "k": 2}),
                ("get_decision", {"decision_id": "dec_001"}),
                ("trace_decision", {"decision_id": "dec_001"}),
                ("check_decision_freshness", {"decision_id": "dec_001"}),
                ("list_stale_decisions", {"limit": 3}),
                ("who_owns", {"module": "fastapi/dependencies"}),
                ("who_knows", {"topic": "dependencies", "limit": 3}),
                ("recent_changes", {"module": "fastapi/dependencies", "since_days": 3650, "limit": 3}),
                ("connection_path", {"from_id": "dec_001", "to_id": "m_docs_en_docs"}),
                ("key_connectors", {"limit": 3}),
                ("flag_for_review", {"decision_id": "dec_001", "note": "Probe test review request"}),
            ]

            print(f"{'Status':<8} {'Tool Name':<28} {'Summary'}")
            print("-" * 80)

            # 1. Call each expected tool with valid sample arguments
            for name, args in expected_tools:
                call_res = await session.call_tool(name, args)
                if not call_res.content or not hasattr(call_res.content[0], "text"):
                    raise ValueError(f"Tool {name} returned empty or invalid content: {call_res}")

                raw_text = call_res.content[0].text
                tr = ToolResult.model_validate_json(raw_text)

                status_str = "PASS" if tr.ok else "FAIL"
                print(f"[{status_str}]   {name:<28} {tr.summary}")
                if not tr.ok:
                    raise AssertionError(f"Tool {name} unexpectedly returned ok=False: {tr.summary}")

            # 2. Deliberate unknown-id call to verify ok=False handling
            unknown_call_res = await session.call_tool("get_decision", {"decision_id": "dec_unknown_probe_id"})
            raw_text = unknown_call_res.content[0].text
            unknown_tr = ToolResult.model_validate_json(raw_text)

            status_str = "PASS" if not unknown_tr.ok else "FAIL"
            print(f"[{status_str}]   {'get_decision (unknown id)':<28} {unknown_tr.summary}")

            if unknown_tr.ok:
                raise AssertionError("Expected deliberate unknown-id call to return ok=False, but got ok=True")

    print("\nAll 11 tools + unknown ID probe PASSED successfully.", flush=True)


def main() -> None:
    asyncio.run(run_probe())


if __name__ == "__main__":
    main()
