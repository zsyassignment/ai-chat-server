"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.conversation.service import ConversationService
from app.db.database import Database
from app.graph.builder import GraphRuntime
from app.graph.context import GraphContext
from app.llm.client import ChatClient, EmbeddingClient
from app.memory.service import MemoryService
from app.rag.store import KnowledgeStore
from app.scheduling.service import ReminderService
from app.skills.service import SkillService
from app.tools.implementations import LearningTools
from app.tools.web_search import TavilyWebSearch


@dataclass
class ApplicationRuntime:
    settings: Settings
    database: Database
    llm: ChatClient
    embeddings: EmbeddingClient
    memory: MemoryService
    conversations: ConversationService
    knowledge: KnowledgeStore
    web_search: TavilyWebSearch
    reminders: ReminderService
    skills: SkillService
    tools: LearningTools
    graph_runtime: GraphRuntime

    @property
    def graph(self):
        return self.graph_runtime.graph

    def close(self) -> None:
        self.reminders.close()
        self.graph_runtime.close()
        self.knowledge.close()


def build_runtime(settings: Settings | None = None) -> ApplicationRuntime:
    resolved = settings or get_settings()
    database = Database(resolved.database_path)
    llm = ChatClient(resolved)
    embeddings = EmbeddingClient(resolved)
    memory = MemoryService(database)
    conversations = ConversationService(
        database, llm, recent_limit=resolved.conversation_recent_messages,
        token_budget=resolved.conversation_token_budget,
        summary_trigger_tokens=resolved.conversation_summary_trigger_tokens,
    )
    knowledge = KnowledgeStore(resolved, database, embeddings)
    web_search = TavilyWebSearch(resolved)
    reminders = ReminderService(database)
    skills = SkillService(resolved.skills_dir)
    tools = LearningTools(knowledge, memory, web_search)
    context = GraphContext(resolved, database, llm, memory, conversations, knowledge, tools, reminders, skills)
    graph_runtime = GraphRuntime(context)
    return ApplicationRuntime(resolved, database, llm, embeddings, memory, conversations, knowledge, web_search, reminders, skills, tools, graph_runtime)
