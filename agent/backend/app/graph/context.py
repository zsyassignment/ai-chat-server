"""Runtime dependencies injected into graph nodes."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.conversation.service import ConversationService
from app.db.database import Database
from app.llm.client import ChatClient
from app.memory.service import MemoryService
from app.rag.store import KnowledgeStore
from app.scheduling.service import ReminderService
from app.skills.service import SkillService
from app.tools.implementations import LearningTools


@dataclass
class GraphContext:
    settings: Settings
    database: Database
    llm: ChatClient
    memory: MemoryService
    conversations: ConversationService
    knowledge: KnowledgeStore
    tools: LearningTools
    reminders: ReminderService
    skills: SkillService
