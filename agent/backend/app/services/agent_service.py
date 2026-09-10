"""Execute/resume LangGraph runs and expose public events."""

from __future__ import annotations

from typing import Any, Dict, Generator, Iterable, List

from langgraph.types import Command, Overwrite

from app.core.ids import new_id, normalize_id
from app.db.database import Database
from app.services.runtime import ApplicationRuntime


class AgentService:
    def __init__(self, runtime: ApplicationRuntime):
        self.runtime = runtime
        self.database: Database = runtime.database

    def run(self, *, user_id: str, thread_id: str, question: str, history: List[Dict[str, str]] | None = None) -> Generator[Dict[str, Any], None, None]:
        user = normalize_id(user_id, "guest")
        thread = normalize_id(thread_id, new_id("thread"))
        run_id = self.database.create_run(user, thread, question)
        context = self.runtime.conversations.prepare_turn(user, thread, question, _sanitize_history(history), run_id=run_id)
        config = {"configurable": {"thread_id": thread}}
        input_state = {
            "user_id": user, "thread_id": thread, "run_id": run_id, "question": question.strip(),
            "original_question": question.strip(), "standalone_question": question.strip(),
            "resolved_references": {}, "contextualization_confidence": 1.0,
            "history": context["recent_messages"], "conversation_summary": context["summary"],
            "intent": "chat", "profile": {}, "active_plan": None,
            "learning_events": [], "research_tasks": [], "research_task": "", "research_outputs": Overwrite([]),
            "research_messages": [], "pending_tool_calls": [], "research_iterations": 0,
            "research_tool_calls": 0, "research_should_continue": True, "research_stop_reason": "",
            "active_skill": {}, "skill_context": "",
            "search_query": "", "rewritten_query": "", "retrieval_hits": [], "retrieval_mode": "",
            "retrieval_reason": "", "retrieval_diagnostics": {}, "retrieval_weak": True,
            "retrieval_quality": "empty", "rewrite_count": 0,
            "retrieval_policy": "auto", "evidence_action": "", "evidence_reason": "",
            "web_results": [], "web_error": "", "web_search_count": 0,
            "max_rewrites": self.runtime.settings.max_rewrite_count, "draft_plan": {},
            "plan_approved": False, "saved_plan": {}, "quiz": {}, "draft_answer": "",
            "reflection": {}, "final_answer": "", "pending_interrupt": {},
            "errors": Overwrite([]), "trace": Overwrite([]),
        }
        yield {"event": "run_started", "data": {"run_id": run_id, "thread_id": thread}}
        yield from self._stream(input_state, config, run_id)

    def resume(self, *, thread_id: str, run_id: str, approved: bool) -> Generator[Dict[str, Any], None, None]:
        config = {"configurable": {"thread_id": normalize_id(thread_id, "default")}}
        yield {"event": "run_resumed", "data": {"run_id": run_id, "approved": approved}}
        yield from self._stream(Command(resume={"approved": approved}), config, run_id)

    def state(self, thread_id: str) -> Dict[str, Any]:
        config = {"configurable": {"thread_id": normalize_id(thread_id, "default")}}
        snapshot = self.runtime.graph.get_state(config)
        return {
            "values": _public_state(snapshot.values), "next": list(snapshot.next),
            "interrupts": [item.value for item in snapshot.interrupts],
        }

    def _stream(self, input_value: Any, config: Dict[str, Any], run_id: str) -> Generator[Dict[str, Any], None, None]:
        step = 0
        try:
            for mode, payload in self.runtime.graph.stream(input_value, config, stream_mode=["custom", "updates"]):
                if mode == "custom":
                    step += 1
                    event = str(payload.get("event", "node_event"))
                    node = str(payload.get("node", ""))
                    self.database.add_step(run_id, step, node, event, payload)
                    yield {"event": event, "data": payload}
                    continue
                if "__interrupt__" in payload:
                    value = payload["__interrupt__"][0].value
                    step += 1
                    self.database.add_step(run_id, step, "interrupt", "interrupt", value)
                    self.database.update_run(run_id, status="interrupted")
                    yield {"event": "interrupt", "data": {"run_id": run_id, **value}}
            snapshot = self.runtime.graph.get_state(config)
            if not snapshot.next:
                answer = str(snapshot.values.get("final_answer", ""))
                intent = str(snapshot.values.get("intent", ""))
                self.runtime.conversations.complete_turn(
                    str(snapshot.values.get("user_id", "guest")),
                    str(snapshot.values.get("thread_id", config["configurable"]["thread_id"])),
                    answer,
                    run_id,
                )
                self.database.update_run(run_id, status="completed", intent=intent, answer=answer)
                yield {"event": "done", "data": {"run_id": run_id, "thread_id": config["configurable"]["thread_id"], "intent": intent, "answer": answer}}
        except Exception as exc:
            self.database.update_run(run_id, status="failed", error=str(exc))
            yield {"event": "error", "data": {"run_id": run_id, "message": str(exc)}}


def _sanitize_history(history: Any) -> List[Dict[str, str]]:
    if not isinstance(history, list): return []
    clean = []
    for item in history[-12:]:
        if not isinstance(item, dict): continue
        role, content = str(item.get("role", "")), str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            clean.append({"role": role, "content": content[:2000]})
    return clean


def _public_state(values: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {"user_id", "thread_id", "run_id", "intent", "question", "original_question", "standalone_question", "contextualization_confidence", "conversation_summary", "search_query", "retrieval_mode", "retrieval_quality", "retrieval_policy", "evidence_action", "evidence_reason", "rewrite_count", "web_results", "web_error", "web_search_count", "draft_plan", "plan_approved", "saved_plan", "quiz", "final_answer", "errors"}
    return {key: value for key, value in values.items() if key in allowed}
