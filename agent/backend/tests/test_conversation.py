from __future__ import annotations

from dataclasses import replace

from app.conversation.service import ConversationService, estimate_tokens
from app.db.database import Database
from app.llm.client import ChatClient
from app.services.agent_service import AgentService


def test_server_persists_turns_and_restores_recent_context(runtime):
    service = AgentService(runtime)
    list(service.run(user_id="alice", thread_id="memory-thread", question="我在研究 Qdrant 的过滤机制"))
    list(service.run(user_id="alice", thread_id="memory-thread", question="那它有什么作用？"))

    rows = runtime.database.list_conversation_messages("alice", "memory-thread")
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    second_run = runtime.database.get_run(rows[2]["run_id"])
    contextualization = next(step for step in second_run["steps"] if step["event_type"] == "contextualization")
    assert "Qdrant" in contextualization["payload"]["standalone"]


def test_rolling_summary_tracks_version_and_coverage(settings):
    database = Database(settings.database_path)
    service = ConversationService(database, ChatClient(settings), recent_limit=2, token_budget=80, summary_trigger_tokens=20)
    for index in range(6):
        database.add_conversation_message("alice", "summary-thread", "user", f"我想学习 LangGraph，第 {index} 个目标必须完成。")
        database.add_conversation_message("alice", "summary-thread", "assistant", f"记录目标 {index}。")
    first = service.maybe_summarize("alice", "summary-thread")
    assert first["version"] == 1
    assert first["through_sequence"] == 10
    assert first["summary"]["user_goals"]

    for index in range(2):
        database.add_conversation_message("alice", "summary-thread", "user", f"我决定采用 RRF 方案 {index}。")
        database.add_conversation_message("alice", "summary-thread", "assistant", "已确认。")
    second = service.maybe_summarize("alice", "summary-thread")
    assert second["version"] == 2
    assert second["through_sequence"] > first["through_sequence"]


def test_recent_context_obeys_count_and_token_budget(settings):
    database = Database(settings.database_path)
    service = ConversationService(database, ChatClient(settings), recent_limit=3, token_budget=10, summary_trigger_tokens=1000)
    for value in ("one two", "three four", "five six", "seven eight"):
        database.add_conversation_message("alice", "budget-thread", "user", value)
    context = service.context("alice", "budget-thread")
    assert len(context["recent_messages"]) <= 3
    assert context["estimated_tokens"] <= 10
    assert estimate_tokens("中文") >= 2


def test_contextualization_keeps_clear_question_and_resolves_pronoun(settings):
    service = ConversationService(Database(settings.database_path), ChatClient(settings))
    clear = service.contextualize("Qdrant 如何做 metadata filter？", {}, [])
    assert clear["standalone_question"] == "Qdrant 如何做 metadata filter？"
    resolved = service.contextualize(
        "那它有什么限制？", {},
        [{"role": "user", "content": "解释一下 Qdrant 的向量过滤机制"}],
    )
    assert "Qdrant" in resolved["standalone_question"]
    assert resolved["confidence"] > 0.5


def test_summary_reads_oldest_unsummarized_messages_without_gaps(settings):
    database = Database(settings.database_path)
    service = ConversationService(database, ChatClient(settings), recent_limit=2, token_budget=100, summary_trigger_tokens=5)
    for index in range(30):
        database.add_conversation_message("alice", "long-thread", "user", f"目标 {index} 必须完成")
    summary = service.maybe_summarize("alice", "long-thread")
    assert summary["through_sequence"] == 28
    assert "目标 0" in summary["summary"]["narrative"] or summary["summary"]["user_goals"]
