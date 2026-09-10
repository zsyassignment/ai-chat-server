"""Typed state and reducers for the LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Literal, TypedDict


class LearningState(TypedDict, total=False):
    user_id: str
    thread_id: str
    run_id: str
    question: str
    original_question: str
    standalone_question: str
    resolved_references: Dict[str, str]
    contextualization_confidence: float
    history: List[Dict[str, str]]
    conversation_summary: Dict[str, Any]
    intent: Literal["chat", "knowledge_qa", "web_search", "reminder", "create_plan", "quiz", "progress", "update_progress", "deep_research"]
    profile: Dict[str, Any]
    active_plan: Dict[str, Any] | None
    learning_events: List[Dict[str, Any]]
    research_tasks: List[str]
    research_task: str
    research_outputs: Annotated[List[Dict[str, Any]], operator.add]
    research_messages: List[Dict[str, Any]]
    pending_tool_calls: List[Dict[str, Any]]
    research_iterations: int
    research_tool_calls: int
    research_should_continue: bool
    research_stop_reason: str
    active_skill: Dict[str, Any]
    skill_context: str
    search_query: str
    rewritten_query: str
    retrieval_hits: List[Dict[str, Any]]
    retrieval_mode: str
    retrieval_reason: str
    retrieval_diagnostics: Dict[str, Any]
    retrieval_weak: bool
    retrieval_quality: Literal["good", "weak", "empty"]
    retrieval_policy: Literal["auto", "local_only", "web_required"]
    evidence_action: Literal["generate", "rewrite", "web", "refuse"]
    evidence_reason: str
    web_results: List[Dict[str, Any]]
    web_error: str
    web_search_count: int
    rewrite_count: int
    max_rewrites: int
    draft_plan: Dict[str, Any]
    plan_approved: bool
    saved_plan: Dict[str, Any]
    quiz: Dict[str, Any]
    draft_answer: str
    reflection: Dict[str, Any]
    final_answer: str
    pending_interrupt: Dict[str, Any]
    errors: Annotated[List[str], operator.add]
    trace: Annotated[List[Dict[str, Any]], operator.add]
