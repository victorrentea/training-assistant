#!/usr/bin/env python3
"""
MCP server exposing the workshop RAG (ChromaDB) to Claude Desktop.
Registered in ~/Library/Application Support/Claude/claude_desktop_config.json.

Run directly: python3 scripts/rag_mcp_server.py
"""
import sys
from pathlib import Path

# Allow importing from daemon/rag without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

server = Server("workshop-rag")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_workshop_materials",
            description=(
                "Search the indexed workshop course materials (PDFs, EPUBs, etc.) "
                "using semantic similarity. Returns the most relevant text chunks "
                "with source file and page number."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The topic or question to search for in the course materials.",
                    }
                },
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "search_workshop_materials":
        raise ValueError(f"Unknown tool: {name}")

    from daemon.rag.retriever import search_materials

    query = arguments["query"]
    chunks = search_materials(query)

    lines = []
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"--- Result {i} | {chunk['source']} p.{chunk['page']} ---")
        lines.append(chunk["content"])
        lines.append("")

    return [types.TextContent(type="text", text="\n".join(lines))]


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.server.stdio.stdio_server(server))
