"""Framework-independent learning tools used by LangGraph nodes."""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.service import MemoryService
from app.rag.store import KnowledgeStore, RetrievalResult
from app.tools.web_search import TavilyWebSearch, WebSearchResult


class LearningTools:
    def __init__(self, knowledge: KnowledgeStore, memory: MemoryService, web: TavilyWebSearch):
        self.knowledge = knowledge
        self.memory = memory
        self.web = web

    def retrieve(self, user_id: str, query: str, limit: int | None = None) -> RetrievalResult:
        return self.knowledge.search(user_id, query, limit)

    def learner_context(self, user_id: str) -> Dict[str, Any]:
        return self.memory.get_context(user_id)

    def search_web(self, query: str, limit: int | None = None) -> WebSearchResult:
        return self.web.search(query, limit)

    def status(self) -> Dict[str, Any]:
        return {
            "web_search": self.web.status(),
            "mcp_server": {
                "enabled": True,
                "name": "learningflow-agent",
                "transport": "stdio + streamable-http",
                "http_endpoint": "/mcp/",
                "tools": [
                    "search_private_knowledge", "list_knowledge_documents", "search_web",
                    "get_learning_plan", "update_learning_progress",
                    "create_learning_reminder", "list_learning_reminders", "list_agent_skills",
                ],
                "resources": ["learningflow://capabilities"],
                "prompts": ["answer_with_private_knowledge"],
            },
        }

    def create_plan(self, user_id: str, topic: str, days: int = 7) -> Dict[str, Any]:
        profile = self.memory.get_context(user_id)["profile"]
        level = profile.get("level", "unspecified")
        style = profile.get("style", "balanced")
        stages = [
            ("建立知识地图", f"梳理 {topic} 的核心概念与前置知识"),
            ("掌握核心原理", f"基于资料解释 {topic} 的关键机制"),
            ("完成最小实践", f"实现一个可运行的 {topic} 最小案例"),
            ("拆解关键模块", f"逐项练习 {topic} 的主要组成部分"),
            ("端到端整合", f"完成一条完整流程并记录问题"),
            ("测验与纠错", f"完成测验并复盘薄弱点"),
            ("总结与演示", f"输出总结并完成最终演示"),
        ]
        items = []
        for index in range(max(3, min(days, 14))):
            stage, task = stages[index] if index < len(stages) else ("深化复习", f"复习 {topic} 并完成扩展练习")
            items.append({"day": index + 1, "topic": stage, "task": f"{task}（水平：{level}；风格：{style}）", "done": False})
        return {"title": f"{topic} {len(items)} 天学习计划", "items": items}

    def generate_quiz(self, user_id: str, topic: str, count: int = 3) -> Dict[str, Any]:
        result = self.knowledge.search(user_id, topic, max(2, min(count, 8)))
        questions = []
        for index in range(max(1, min(count, 8))):
            if result.hits:
                hit = result.hits[index % len(result.hits)]
                questions.append({
                    "id": index + 1,
                    "question": f"根据《{hit['filename']}》的相关内容，解释核心概念并举例。",
                    "reference": hit["content"][:240],
                    "source": {key: hit.get(key) for key in ("document_id", "filename", "chunk_index", "page", "score")},
                })
            else:
                questions.append({"id": index + 1, "question": f"解释 {topic} 的一个核心概念和适用场景。", "reference": "", "source": None})
        return {"topic": topic, "questions": questions, "retrieval_mode": result.mode}
