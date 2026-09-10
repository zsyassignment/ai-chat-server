"""Build and compile the standalone adaptive learning LangGraph."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.graph.context import GraphContext
from app.graph.nodes.workflow import WorkflowNodes
from app.graph.state import LearningState


class GraphRuntime:
    def __init__(self, context: GraphContext):
        self.context = context
        self.connection = sqlite3.connect(str(context.settings.checkpoint_path), check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.graph = build_graph(context).compile(checkpointer=self.checkpointer)

    def close(self) -> None:
        self.connection.close()


def build_graph(context: GraphContext) -> StateGraph:
    nodes = WorkflowNodes(context)
    graph = StateGraph(LearningState)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("contextualize_question", nodes.contextualize_question)
    graph.add_node("route_intent", nodes.route_intent)
    graph.add_node("direct_chat", nodes.direct_chat)
    graph.add_node("web_search", nodes.web_search)
    graph.add_node("reminder", nodes.reminder)
    graph.add_node("prepare_query", nodes.prepare_query)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade_retrieval", nodes.grade_retrieval)
    graph.add_node("decide_evidence", nodes.decide_evidence)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("generate_grounded", nodes.generate_grounded)
    graph.add_node("draft_plan", nodes.draft_plan)
    graph.add_node("approve_plan", nodes.approve_plan)
    graph.add_node("persist_plan", nodes.persist_plan)
    graph.add_node("progress", nodes.progress)
    graph.add_node("update_progress", nodes.update_progress)
    graph.add_node("quiz", nodes.quiz)
    graph.add_node("plan_research", nodes.plan_research)
    graph.add_node("research_worker", nodes.research_worker)
    graph.add_node("research_reason", nodes.research_reason)
    graph.add_node("research_act", nodes.research_act)
    graph.add_node("research_critic", nodes.research_critic)
    graph.add_node("synthesize_research", nodes.synthesize_research)
    graph.add_node("reflect", nodes.reflect)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "contextualize_question")
    graph.add_edge("contextualize_question", "route_intent")
    graph.add_conditional_edges("route_intent", _route_intent, {
        "chat": "direct_chat", "knowledge_qa": "prepare_query", "web_search": "prepare_query", "reminder": "reminder", "create_plan": "draft_plan",
        "quiz": "quiz", "progress": "progress", "update_progress": "update_progress",
        "deep_research": "plan_research",
    })
    graph.add_edge("prepare_query", "retrieve")
    graph.add_edge("retrieve", "grade_retrieval")
    graph.add_edge("grade_retrieval", "decide_evidence")
    graph.add_conditional_edges("decide_evidence", _route_evidence, {
        "generate": "generate_grounded", "rewrite": "rewrite_query",
        "web": "web_search", "refuse": "generate_grounded",
    })
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("web_search", "generate_grounded")
    graph.add_conditional_edges("plan_research", _fan_out_research, ["research_worker"])
    graph.add_edge("research_worker", "research_reason")
    graph.add_conditional_edges("research_reason", _route_research_reason, {
        "act": "research_act", "synthesize": "synthesize_research",
    })
    graph.add_edge("research_act", "research_critic")
    graph.add_conditional_edges("research_critic", _route_research_critic, {
        "continue": "research_reason", "synthesize": "synthesize_research",
    })
    graph.add_edge("draft_plan", "approve_plan")
    graph.add_edge("approve_plan", "persist_plan")
    for source in ("direct_chat", "reminder", "generate_grounded", "persist_plan", "progress", "update_progress", "quiz", "synthesize_research"):
        graph.add_edge(source, "reflect")
    graph.add_edge("reflect", "finalize")
    graph.add_edge("finalize", END)
    return graph


def _route_intent(state: LearningState) -> str:
    return state.get("intent", "chat")


def _route_evidence(state: LearningState) -> Literal["generate", "rewrite", "web", "refuse"]:
    return state.get("evidence_action", "refuse")


def _fan_out_research(state: LearningState):
    return [Send("research_worker", {**state, "research_task": task}) for task in state.get("research_tasks", [])]


def _route_research_reason(state: LearningState) -> Literal["act", "synthesize"]:
    return "act" if state.get("pending_tool_calls") else "synthesize"


def _route_research_critic(state: LearningState) -> Literal["continue", "synthesize"]:
    return "continue" if state.get("research_should_continue") else "synthesize"
