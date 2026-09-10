from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.db.database import Database
from app.mcp_server.server import create_mcp_server


def test_learningflow_mcp_server_exposes_and_calls_hybrid_rag(settings):
    database = Database(settings.database_path)
    database.add_document(
        "alice",
        "agent-loop.md",
        "text/markdown",
        [{"content": "Agent Loop uses Observation to feed tool results into the next reasoning step.", "section": "Agent Loop"}],
    )

    async def scenario():
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(root / "backend"),
            "DATA_DIR": str(settings.data_dir),
            "DATABASE_PATH": str(settings.database_path),
            "CHECKPOINT_PATH": str(settings.checkpoint_path),
            "QDRANT_MODE": "local",
            "QDRANT_PATH": str(settings.qdrant_path),
            "EMBEDDING_PROVIDER": "disabled",
            "EMBEDDING_API_KEY": "",
        })
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=root,
            env=env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "learningflow-agent"

                tools = await session.list_tools()
                tool_map = {tool.name: tool for tool in tools.tools}
                assert {
                    "search_private_knowledge", "list_knowledge_documents", "search_web",
                    "get_learning_plan", "update_learning_progress",
                    "create_learning_reminder", "list_learning_reminders", "list_agent_skills",
                } == set(tool_map)
                schema = tool_map["search_private_knowledge"].inputSchema
                assert set(schema["required"]) == {"user_id", "query"}

                response = await session.call_tool(
                    "search_private_knowledge",
                    {"user_id": "alice", "query": "Agent Loop Observation", "limit": 3},
                )
                assert response.isError is False
                payload = (response.structuredContent or {}).get("result") or json.loads(response.content[0].text)
                assert payload["mode"] == "keyword"
                assert payload["results"][0]["filename"] == "agent-loop.md"
                assert payload["results"][0]["citation"] == "S1"

                run_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
                created = await session.call_tool("create_learning_reminder", {
                    "user_id": "alice", "message": "复习 MCP", "run_at": run_at,
                    "timezone": "Asia/Shanghai", "repeat": "once",
                })
                created_payload = created.structuredContent["result"]
                assert created_payload["created"] is True
                listed = await session.call_tool("list_learning_reminders", {"user_id": "alice"})
                assert listed.structuredContent["result"]["reminders"][0]["message"] == "复习 MCP"

                resources = await session.list_resources()
                assert any(str(item.uri) == "learningflow://capabilities" for item in resources.resources)
                resource = await session.read_resource("learningflow://capabilities")
                assert "Qdrant dense retrieval" in resource.contents[0].text

                prompts = await session.list_prompts()
                assert any(item.name == "answer_with_private_knowledge" for item in prompts.prompts)
                prompt = await session.get_prompt(
                    "answer_with_private_knowledge",
                    {"question": "What is Observation?", "user_id": "alice"},
                )
                assert "search_private_knowledge" in prompt.messages[0].content.text

    asyncio.run(scenario())


def test_learningflow_mcp_streamable_http_shares_application_runtime(runtime):
    runtime.database.add_document(
        "alice", "shared.md", "text/markdown",
        [{"content": "Streamable HTTP shares the existing hybrid RAG runtime.", "section": "MCP"}],
    )

    async def scenario():
        server = create_mcp_server(runtime, http_path="/")

        @asynccontextmanager
        async def lifespan(app):
            async with server.session_manager.run():
                yield

        app = FastAPI(lifespan=lifespan)
        app.mount("/mcp", server.streamable_http_app())
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8010") as http_client:
                async with streamable_http_client(
                    "http://127.0.0.1:8010/mcp/", http_client=http_client
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == "learningflow-agent"
                        response = await session.call_tool(
                            "search_private_knowledge",
                            {"user_id": "alice", "query": "Streamable HTTP hybrid RAG"},
                        )
                        payload = response.structuredContent["result"]
                        assert response.isError is False
                        assert payload["results"][0]["filename"] == "shared.md"

    asyncio.run(scenario())
