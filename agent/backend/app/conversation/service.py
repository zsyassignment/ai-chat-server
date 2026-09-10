"""Layered conversation memory: raw messages, rolling summary, and recent window."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.db.database import Database
from app.llm.client import ChatClient

_SUMMARY_KEYS = ("current_topic", "user_goals", "confirmed_decisions", "constraints", "open_questions", "narrative")


class ConversationService:
    def __init__(self, database: Database, llm: ChatClient, *, recent_limit: int = 10, token_budget: int = 6000, summary_trigger_tokens: int = 4000):
        self.database = database
        self.llm = llm
        self.recent_limit = recent_limit
        self.token_budget = token_budget
        self.summary_trigger_tokens = summary_trigger_tokens

    def prepare_turn(self, user_id: str, thread_id: str, question: str, client_history: List[Dict[str, str]] | None = None, run_id: str = "") -> Dict[str, Any]:
        if not self.database.list_conversation_messages(user_id, thread_id, limit=1) and client_history:
            history = list(client_history)
            if history and history[-1].get("role") == "user" and history[-1].get("content", "").strip() == question.strip():
                history.pop()
            for item in history[-20:]:
                if item.get("role") in {"user", "assistant"} and str(item.get("content", "")).strip():
                    self.database.add_conversation_message(user_id, thread_id, item["role"], str(item["content"])[:10000])
        context = self.context(user_id, thread_id)
        self.database.add_conversation_message(user_id, thread_id, "user", question.strip(), run_id=run_id)
        return context

    def complete_turn(self, user_id: str, thread_id: str, answer: str, run_id: str) -> None:
        if answer.strip():
            self.database.add_conversation_message(user_id, thread_id, "assistant", answer.strip(), run_id=run_id)
        self.maybe_summarize(user_id, thread_id)

    def context(self, user_id: str, thread_id: str) -> Dict[str, Any]:
        summary = self.database.get_conversation_summary(user_id, thread_id)
        rows = self.database.list_conversation_messages(user_id, thread_id, limit=max(self.recent_limit * 3, 20))
        selected, used = [], 0
        for row in reversed(rows):
            cost = int(row.get("token_estimate", 0))
            if selected and (len(selected) >= self.recent_limit or used + cost > self.token_budget):
                break
            selected.append({"role": row["role"], "content": row["content"]})
            used += cost
        return {"summary": (summary or {}).get("summary", {}), "recent_messages": list(reversed(selected)), "estimated_tokens": used}

    def contextualize(self, question: str, summary: Dict[str, Any], recent: List[Dict[str, str]]) -> Dict[str, Any]:
        if self.llm.enabled:
            result = self.llm.complete_json(
                "Rewrite the latest user message as a standalone question using only supplied context. Return JSON only with standalone_question, resolved_references (object), confidence (0-1). Do not answer it.",
                {"summary": summary, "recent_messages": recent[-10:], "latest_message": question},
                max_tokens=260,
            )
            standalone = str((result or {}).get("standalone_question", "")).strip()
            if standalone:
                return {
                    "standalone_question": standalone,
                    "resolved_references": (result or {}).get("resolved_references", {}),
                    "confidence": max(0.0, min(float((result or {}).get("confidence", 0.5)), 1.0)),
                }
        return _offline_contextualize(question, summary, recent)

    def maybe_summarize(self, user_id: str, thread_id: str) -> Dict[str, Any] | None:
        previous = self.database.get_conversation_summary(user_id, thread_id)
        through = int((previous or {}).get("through_sequence", 0))
        pending = self.database.list_conversation_messages_after(user_id, thread_id, through)
        pending_tokens = sum(int(item.get("token_estimate", 0)) for item in pending)
        if pending_tokens <= self.summary_trigger_tokens and len(pending) <= self.recent_limit * 2:
            return previous
        candidates = pending[:-self.recent_limit]
        if not candidates:
            return previous
        old_summary = (previous or {}).get("summary", {})
        summary = self._summarize(old_summary, candidates)
        return self.database.save_conversation_summary(
            user_id, thread_id, summary, through_sequence=int(candidates[-1]["sequence"]),
        )

    def _summarize(self, previous: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.llm.enabled:
            result = self.llm.complete_json(
                "Update a factual conversation memory. Return JSON with current_topic, user_goals, confirmed_decisions, constraints, open_questions, narrative. Distinguish user facts from assistant proposals and never invent facts.",
                {"previous_summary": previous, "messages": [{"role": row["role"], "content": row["content"]} for row in messages]},
                max_tokens=900,
            )
            if result:
                return _normalize_summary(result)
        return _offline_summary(previous, messages)


def _offline_contextualize(question: str, summary: Dict[str, Any], recent: List[Dict[str, str]]) -> Dict[str, Any]:
    ambiguous = bool(re.search(r"(^|[，。！？\s])(它|他|她|这|那|这个|那个|这点|那点|上面|刚才|继续|然后)", question)) or len(question.strip()) < 8
    if not ambiguous:
        return {"standalone_question": question, "resolved_references": {}, "confidence": 1.0}
    previous = next((
        item["content"] for item in reversed(recent)
        if item.get("role") == "user" and item.get("content", "").strip() != question.strip()
    ), "")
    topic = str(summary.get("current_topic", "")).strip()
    anchor = previous or topic
    if not anchor:
        return {"standalone_question": question, "resolved_references": {}, "confidence": 0.25}
    return {
        "standalone_question": f"结合上一轮关于“{anchor[:240]}”的上下文，{question}",
        "resolved_references": {"context": anchor[:240]},
        "confidence": 0.7,
    }


def _offline_summary(previous: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    users = [row["content"] for row in messages if row["role"] == "user"]
    narrative_parts = [str(previous.get("narrative", "")).strip(), *users[-6:]]
    goals = list(previous.get("user_goals", []))
    goals.extend(text[:300] for text in users if re.search(r"我想|目标|希望|需要", text))
    decisions = list(previous.get("confirmed_decisions", []))
    decisions.extend(text[:300] for text in users if re.search(r"就用|决定|确定|采用", text))
    constraints = list(previous.get("constraints", []))
    constraints.extend(text[:300] for text in users if re.search(r"不要|必须|至少|一周|限制", text))
    questions = [text[:300] for text in users if text.rstrip().endswith(("?", "？"))]
    return _normalize_summary({
        "current_topic": users[-1][:200] if users else previous.get("current_topic", ""),
        "user_goals": goals,
        "confirmed_decisions": decisions,
        "constraints": constraints,
        "open_questions": questions[-5:],
        "narrative": " | ".join(part for part in narrative_parts if part)[-2000:],
    })


def _normalize_summary(value: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in _SUMMARY_KEYS:
        raw = value.get(key, [] if key not in {"current_topic", "narrative"} else "")
        if key in {"current_topic", "narrative"}:
            result[key] = str(raw)[:3000]
        else:
            items = raw if isinstance(raw, list) else [raw]
            result[key] = list(dict.fromkeys(str(item)[:500] for item in items if str(item).strip()))[-20:]
    return result


def estimate_tokens(text: str) -> int:
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = max(0, len(text) - chinese)
    return max(1, chinese + (other + 3) // 4)
