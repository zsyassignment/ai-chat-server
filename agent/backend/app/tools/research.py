"""Tool schemas and safe execution for the deep-research ReAct loop."""

from __future__ import annotations

from typing import Any, Dict, List

from app.graph.context import GraphContext


def _schema(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False,
    }}}


RESEARCH_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _schema("search_private_knowledge", "Search uploaded private documents for project-specific evidence.", {
        "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
    }, ["query"]),
    _schema("list_knowledge_documents", "List the user's uploaded private documents.", {}, []),
    _schema("search_web", "Search current public web information through Tavily.", {
        "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
    }, ["query"]),
    _schema("get_learning_plan", "Read the user's active learning plan.", {}, []),
    _schema("update_learning_progress", "Mark a learning-plan day complete or incomplete.", {
        "day": {"type": "integer", "minimum": 1, "maximum": 365}, "done": {"type": "boolean", "default": True},
    }, ["day"]),
    _schema("create_learning_reminder", "Create a persistent one-time or daily reminder using an ISO-8601 datetime.", {
        "message": {"type": "string"}, "run_at": {"type": "string"}, "timezone": {"type": "string", "default": "Asia/Shanghai"},
        "repeat": {"type": "string", "enum": ["once", "daily"], "default": "once"}, "plan_day": {"type": ["integer", "null"]},
    }, ["message", "run_at"]),
    _schema("list_learning_reminders", "List the user's scheduled reminders.", {}, []),
]


def execute_research_tool(context: GraphContext, user_id: str, call: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one allowlisted research/Skill tool and normalize its observation."""
    name = str(call.get("name", ""))
    arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    if name == "search_private_knowledge":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"tool": name, "error": "query is required"}
        result = context.tools.retrieve(user_id, query, _limit(arguments))
        return {"tool": name, "query": query, "mode": result.mode, "hits": result.hits, "weak": result.weak, "error": result.reason}
    if name == "list_knowledge_documents":
        return {"tool": name, "documents": context.database.list_documents(user_id), "error": ""}
    if name == "search_web":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"tool": name, "error": "query is required"}
        result = context.tools.search_web(query, _limit(arguments))
        return {"tool": name, "query": query, "results": result.results, "answer": result.answer, "error": result.error}
    if name == "get_learning_plan":
        return {"tool": name, "plan": context.database.get_active_plan(user_id), "error": ""}
    if name == "update_learning_progress":
        try:
            day = max(1, min(int(arguments.get("day")), 365))
        except (TypeError, ValueError):
            return {"tool": name, "error": "valid day is required"}
        done = bool(arguments.get("done", True))
        plan = context.memory.update_progress(user_id, day, done)
        return {"tool": name, "updated": plan is not None, "day": day, "done": done, "plan": plan, "error": "" if plan else "plan day not found"}
    if name == "create_learning_reminder":
        try:
            reminder = context.reminders.create(
                user_id, str(arguments.get("message", "")), str(arguments.get("run_at", "")),
                timezone_name=str(arguments.get("timezone", "Asia/Shanghai")),
                repeat=str(arguments.get("repeat", "once")), plan_day=arguments.get("plan_day"),
            )
            return {"tool": name, "created": True, "reminder": reminder, "error": ""}
        except ValueError as exc:
            return {"tool": name, "created": False, "error": str(exc)}
    if name == "list_learning_reminders":
        return {"tool": name, "reminders": context.reminders.list(user_id), "error": ""}
    return {"tool": name, "error": "tool is not allowed in deep research"}


def research_tool_names() -> set[str]:
    return {item["function"]["name"] for item in RESEARCH_TOOL_SCHEMAS}


def _limit(arguments: Dict[str, Any]) -> int:
    try:
        return max(1, min(int(arguments.get("limit", 4)), 8))
    except (TypeError, ValueError):
        return 4
