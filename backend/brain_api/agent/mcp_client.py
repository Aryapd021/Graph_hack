"""MCP client utilities, tool execution, and Gemini FunctionDeclaration conversion.

Per ARCHITECTURE.md sections 11, 12, 17 (Gate G6) & Task B8:
- Keeps one stdio session for the app lifetime via mcp_manager.
- call_tool(name, args) returns a parsed ToolResult.
- Handles a crashed child by returning ToolResult(ok=False) and logging to stderr.
- Converts MCP Tool definitions into Gemini FunctionDeclaration instances.
"""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from google.genai import types

from brain_api.mcp_manager import mcp_manager
from brain_core.models import GraphPayload, ToolResult

logger = logging.getLogger("brain_api.agent.mcp_client")


def sanitize_schema_for_gemini(schema: Any) -> Any:
    """Recursively strip keywords not supported by Gemini's schema converter.

    Why: FastMCP and Pydantic generate 'title', '$schema', '$defs', and 'definitions'
    metadata which can trigger warnings or schema rejections in Gemini tool compilation.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: Dict[str, Any] = {}
    for key, value in schema.items():
        if key in ("title", "$schema", "definitions", "$defs"):
            continue
        if isinstance(value, dict):
            cleaned[key] = sanitize_schema_for_gemini(value)
        elif isinstance(value, list):
            cleaned[key] = [sanitize_schema_for_gemini(item) for item in value]
        else:
            cleaned[key] = value

    return cleaned


def convert_tool_to_function_declaration(tool: Any) -> types.FunctionDeclaration:
    """Convert an MCP Tool instance or tool dictionary to a Gemini FunctionDeclaration.

    Why: Gate G6 and Section 12 require converting each MCP tool's inputSchema into
    an accepted Gemini FunctionDeclaration for the agent reasoning loop.
    """
    if hasattr(tool, "name"):
        name = tool.name
        description = getattr(tool, "description", "") or ""
        raw_schema = getattr(tool, "input_schema", None) or getattr(tool, "parameters", {})
    elif isinstance(tool, dict):
        name = tool.get("name", "")
        description = tool.get("description", "") or ""
        raw_schema = tool.get("input_schema") or tool.get("inputSchema") or tool.get("parameters", {})
    else:
        raise ValueError(f"Unsupported tool type: {type(tool)}")

    cleaned_schema = sanitize_schema_for_gemini(raw_schema)
    json_schema = types.JSONSchema(**cleaned_schema)
    parameters_schema = types.Schema.from_json_schema(json_schema=json_schema)

    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=parameters_schema,
    )


async def get_tool_declarations() -> List[types.FunctionDeclaration]:
    """Retrieve all available MCP tools and convert them to Gemini FunctionDeclarations."""
    session = await mcp_manager.get_session()
    tools_list = await session.list_tools()
    return [convert_tool_to_function_declaration(tool) for tool in tools_list.tools]


async def call_tool(name: str, args: Dict[str, Any]) -> ToolResult:
    """Invoke an MCP tool and return a validated ToolResult.

    Per Task B8:
    Handles child crash or execution error by returning ToolResult(ok=False) and logging to stderr.
    """
    try:
        call_res = await mcp_manager.call_tool(name, args)
        if not call_res or not call_res.content:
            return ToolResult(
                ok=False,
                summary=f"Tool '{name}' returned empty response",
                data={},
                evidence=[],
                graph=GraphPayload(nodes=[], edges=[]),
                cypher_ids=[],
            )

        text_content = call_res.content[0].text
        data = json.loads(text_content)
        return ToolResult.model_validate(data)
    except Exception as exc:
        print(f"Error calling MCP tool '{name}': {exc}", file=sys.stderr, flush=True)
        logger.error(f"Error calling MCP tool '{name}': {exc}", exc_info=True)
        return ToolResult(
            ok=False,
            summary=f"Tool '{name}' failed: {exc}",
            data={},
            evidence=[],
            graph=GraphPayload(nodes=[], edges=[]),
            cypher_ids=[],
        )
