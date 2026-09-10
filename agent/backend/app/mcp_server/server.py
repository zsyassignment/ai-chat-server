"""Publish LearningFlow's private hybrid RAG through the Model Context Protocol.

Standalone stdio mode:
    PYTHONPATH=backend python -m app.mcp_server.server

The FastAPI application also mounts a Streamable HTTP endpoint at /mcp.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.core.config import Settings
from app.core.ids import normalize_id
from app.db.database import Database
from app.llm.client import EmbeddingClient
from app.rag.store import KnowledgeStore
from app.scheduling.service import ReminderService


class MCPKnowledgeRuntime:
    """Minimal standalone runtime sharing the Web application's storage format."""

    def __init__(self, settings: Settings):
        self.database = Database(settings.database_path)
        self.knowledge = KnowledgeStore(settings, self.database, EmbeddingClient(settings))
        self.reminders = ReminderService(self.database)
        self.reminders.start()

    def close(self) -> None:
        self.reminders.close()
        self.knowledge.close()


@asynccontextmanager
async def _standalone_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    runtime = MCPKnowledgeRuntime(Settings.from_env())
    try:
        yield {"runtime": runtime}
    finally:
        runtime.close()


def create_mcp_server(shared_runtime: Any | None = None, *, http_path: str = "/mcp") -> FastMCP:
    """Create an MCP server backed by either shared or lifespan-managed RAG state."""
    server = FastMCP(
        "learningflow-agent",
        instructions=(
            "Use LearningFlow private knowledge, web search, learning-plan, progress, and persistent-reminder tools. "
            "Respect user_id isolation and retrieve evidence before answering questions about uploaded documents."
        ),
        lifespan=None if shared_runtime is not None else _standalone_lifespan,
        streamable_http_path=http_path,
        stateless_http=True,
        json_response=True,
    )

    def knowledge_store() -> KnowledgeStore:
        if shared_runtime is not None:
            return shared_runtime.knowledge
        context = server.get_context()
        runtime: MCPKnowledgeRuntime = context.request_context.lifespan_context["runtime"]
        return runtime.knowledge

    def database() -> Database:
        if shared_runtime is not None:
            return shared_runtime.database
        context = server.get_context()
        runtime: MCPKnowledgeRuntime = context.request_context.lifespan_context["runtime"]
        return runtime.database

    def reminder_service():
        if shared_runtime is not None:
            return shared_runtime.reminders
        context = server.get_context()
        runtime: MCPKnowledgeRuntime = context.request_context.lifespan_context["runtime"]
        return runtime.reminders

    @server.tool(
        name="search_private_knowledge",
        description=(
            "Search one user's private uploaded documents with hybrid retrieval: SQLite FTS5 inverted-index "
            "recall plus Qdrant dense-vector recall, RRF fusion, and optional cross-encoder reranking."
        ),
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def search_private_knowledge(user_id: str, query: str, limit: int = 5) -> Dict[str, Any]:
        """Return grounded private-document excerpts and retrieval diagnostics.

        Args:
            user_id: Owner of the private document collection.
            query: Natural-language retrieval query.
            limit: Number of fused results to return, from 1 to 10.
        """
        safe_user = normalize_id(user_id, "guest")
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("query must not be empty")
        result = knowledge_store().search(safe_user, clean_query, max(1, min(limit, 10)))
        return {
            "query": clean_query,
            "user_id": safe_user,
            "mode": result.mode,
            "weak": result.weak,
            "reason": result.reason,
            "results": [
                {
                    "citation": f"S{index}",
                    "filename": hit["filename"],
                    "page": hit.get("page"),
                    "section": hit.get("section", ""),
                    "content": hit["content"],
                    "score": hit.get("rerank_score", hit.get("rrf_score", hit.get("score", 0.0))),
                    "retrieval_paths": hit.get("retrieval_paths", []),
                }
                for index, hit in enumerate(result.hits, 1)
            ],
            "diagnostics": result.diagnostics or {},
        }

    @server.tool(
        name="list_knowledge_documents",
        description="List documents available in one user's private LearningFlow knowledge base.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def list_knowledge_documents(user_id: str) -> Dict[str, Any]:
        safe_user = normalize_id(user_id, "guest")
        return {"user_id": safe_user, "documents": database().list_documents(safe_user)}

    @server.tool(
        name="search_web",
        description="Search current public web information through Tavily and return titles, excerpts, and URLs.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    )
    def search_web(query: str, limit: int = 5) -> Dict[str, Any]:
        if shared_runtime is None:
            from app.tools.web_search import TavilyWebSearch

            web = TavilyWebSearch(Settings.from_env())
        else:
            web = shared_runtime.web_search
        result = web.search(query.strip(), max(1, min(limit, 10)))
        return {"query": query.strip(), "results": result.results, "answer": result.answer, "error": result.error}

    @server.tool(
        name="get_learning_plan",
        description="Get a user's current learning plan and progress.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def get_learning_plan(user_id: str) -> Dict[str, Any]:
        safe_user = normalize_id(user_id, "guest")
        return {"user_id": safe_user, "plan": database().get_active_plan(safe_user)}

    @server.tool(
        name="update_learning_progress",
        description="Mark one day in a user's active learning plan completed or not completed.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def update_learning_progress(user_id: str, day: int, done: bool = True) -> Dict[str, Any]:
        safe_user = normalize_id(user_id, "guest")
        plan = database().mark_plan_day(safe_user, max(1, min(day, 365)), done)
        return {"updated": plan is not None, "user_id": safe_user, "day": day, "done": done, "plan": plan}

    @server.tool(
        name="create_learning_reminder",
        description=(
            "Create a persistent one-time or daily learning reminder. run_at is an ISO-8601 datetime; "
            "an optional plan_day links the reminder to the active plan."
        ),
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def create_learning_reminder(
        user_id: str, message: str, run_at: str, timezone: str = "Asia/Shanghai",
        repeat: str = "once", plan_day: int | None = None,
    ) -> Dict[str, Any]:
        safe_user = normalize_id(user_id, "guest")
        reminder = reminder_service().create(
            safe_user, message, run_at, timezone_name=timezone, repeat=repeat, plan_day=plan_day,
        )
        return {"created": True, "reminder": reminder}

    @server.tool(
        name="list_learning_reminders",
        description="List a user's scheduled learning reminders.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def list_learning_reminders(user_id: str) -> Dict[str, Any]:
        safe_user = normalize_id(user_id, "guest")
        return {"user_id": safe_user, "reminders": reminder_service().list(safe_user)}

    @server.tool(
        name="list_agent_skills",
        description="List the user's installed declarative Agent Skills, triggers, and allowed tools.",
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def list_agent_skills(user_id: str) -> Dict[str, Any]:
        if shared_runtime is None:
            from app.skills.service import SkillService

            skills = SkillService(Settings.from_env().skills_dir)
        else:
            skills = shared_runtime.skills
        safe_user = normalize_id(user_id, "guest")
        return {"user_id": safe_user, "skills": [skills.public(skill) for skill in skills.list(safe_user)]}

    @server.resource(
        "learningflow://capabilities",
        name="learningflow_capabilities",
        description="Machine-readable description of the LearningFlow MCP service.",
        mime_type="application/json",
    )
    def capabilities() -> Dict[str, Any]:
        """Describe the retrieval pipeline exposed by this MCP server."""
        return {
            "server": "learningflow-agent",
            "tools": [
                "search_private_knowledge", "list_knowledge_documents", "search_web",
                "get_learning_plan", "update_learning_progress",
                "create_learning_reminder", "list_learning_reminders", "list_agent_skills",
            ],
            "pipeline": ["SQLite FTS5", "Qdrant dense retrieval", "RRF", "optional CrossEncoder"],
            "scheduling": ["APScheduler", "SQLite persistence", "restart recovery", "in-app notifications"],
            "tenant_scope": "user_id",
            "citation_format": "S1, S2, ...",
        }

    @server.prompt(
        name="answer_with_private_knowledge",
        description="Prompt template for grounded answers using LearningFlow search results.",
    )
    def answer_with_private_knowledge(question: str, user_id: str = "guest") -> str:
        """Guide an MCP-capable Agent to retrieve before answering."""
        return (
            f"Answer this question for user {user_id}: {question}\n"
            "First call search_private_knowledge with the same user_id. "
            "Use only returned evidence for private facts, cite it as [S1], [S2], and say when evidence is insufficient."
        )

    return server


mcp = create_mcp_server()


if __name__ == "__main__":
    mcp.run(transport="stdio")
