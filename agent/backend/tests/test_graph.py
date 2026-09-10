from __future__ import annotations

from dataclasses import replace

from app.services.agent_service import AgentService


def collect(generator):
    return list(generator)


def test_knowledge_qa_runs_retrieve_grade_rewrite_and_answer(runtime):
    runtime.database.add_document(
        "alice", "agent.md", "text/markdown",
        [{"content": "Agent Loop 的 Observation 把工具结果反馈给下一轮决策。", "page": None, "section": "Agent Loop"}],
    )
    events = collect(AgentService(runtime).run(
        user_id="alice", thread_id="qa-thread", question="根据资料解释 Observation 的作用"
    ))
    names = [event["event"] for event in events]
    assert "retrieval" in names
    assert "retrieval_grade" in names
    assert "query_rewrite" in names  # one hit is intentionally graded weak
    rewrite_event = next(event for event in events if event["event"] == "query_rewrite")
    assert "根据资料" not in rewrite_event["data"]["rewritten"]
    assert names[-1] == "done"
    assert "[S1]" in events[-1]["data"]["answer"]


def test_plan_interrupt_and_resume_persists_plan(runtime):
    service = AgentService(runtime)
    first = collect(service.run(
        user_id="alice", thread_id="plan-thread",
        question="我是初学者，每天学习2小时，帮我制定一周 LangGraph 学习计划",
    ))
    interrupt_event = next(event for event in first if event["event"] == "interrupt")
    assert interrupt_event["data"]["type"] == "plan_approval"
    assert runtime.database.get_active_plan("alice") is None

    resumed = collect(service.resume(
        thread_id="plan-thread", run_id=interrupt_event["data"]["run_id"], approved=True
    ))
    assert resumed[-1]["event"] == "done"
    plan = runtime.database.get_active_plan("alice")
    assert plan is not None
    assert len(plan["items"]) == 7


def test_rejected_plan_is_not_persisted(runtime):
    service = AgentService(runtime)
    first = collect(service.run(user_id="alice", thread_id="reject-thread", question="制定三天 RAG 学习计划"))
    interrupt_event = next(event for event in first if event["event"] == "interrupt")
    resumed = collect(service.resume(thread_id="reject-thread", run_id=interrupt_event["data"]["run_id"], approved=False))
    assert resumed[-1]["event"] == "done"
    assert "取消" in resumed[-1]["data"]["answer"]
    assert runtime.database.get_active_plan("alice") is None


def test_run_trace_is_persisted(runtime):
    events = collect(AgentService(runtime).run(user_id="alice", thread_id="trace-thread", question="你好"))
    run_id = events[0]["data"]["run_id"]
    run = runtime.database.get_run(run_id)
    assert run["status"] == "completed"
    assert run["steps"]
    assert any(step["node"] == "route_intent" for step in run["steps"])


def test_deep_research_fans_out_to_parallel_workers(runtime):
    runtime.database.add_document(
        "alice", "research.md", "text/markdown",
        [
            {"content": "RAG 的核心包括检索和生成。", "section": "原理"},
            {"content": "RAG 实践需要分块、索引和引用。", "section": "实践"},
            {"content": "RAG 的风险包括错误召回和幻觉。", "section": "限制"},
        ],
    )
    events = collect(AgentService(runtime).run(
        user_id="alice", thread_id="research-thread", question="深入研究 RAG 并生成研究报告"
    ))
    names = [event["event"] for event in events]
    assert "research_plan" in names
    assert names.count("research_result") == 3
    assert "research_reason" in names
    assert "research_tool_call" in names
    assert "research_observation" in names
    assert "research_critic" in names
    assert names[-1] == "done"
    assert "研究摘要" in events[-1]["data"]["answer"]


def test_same_thread_does_not_reuse_previous_turn_draft(runtime):
    service = AgentService(runtime)
    first = collect(service.run(user_id="alice", thread_id="same-thread", question="你好"))
    second = collect(service.run(user_id="alice", thread_id="same-thread", question="查看当前学习进度"))
    assert "你问的是" in first[-1]["data"]["answer"]
    assert "还没有活动学习计划" in second[-1]["data"]["answer"]
    second_run = runtime.database.get_run(second[0]["data"]["run_id"])
    assert len([step for step in second_run["steps"] if step["node"] == "route_intent"]) == 1


def test_chat_can_create_and_list_persistent_reminders(runtime):
    service = AgentService(runtime)
    created = collect(service.run(
        user_id="alice", thread_id="reminder-create",
        question="30分钟后提醒我复习 Agent Loop",
    ))
    assert created[-1]["data"]["intent"] == "reminder"
    assert "提醒已创建" in created[-1]["data"]["answer"]

    listed = collect(service.run(
        user_id="alice", thread_id="reminder-list", question="查看我的提醒",
    ))
    assert "复习 Agent Loop" in listed[-1]["data"]["answer"]


def test_react_write_tool_requires_human_approval(runtime, monkeypatch):
    from app.graph.nodes.workflow import WorkflowNodes

    monkeypatch.setattr("app.graph.nodes.workflow.interrupt", lambda payload: {"approved": False})
    result = WorkflowNodes(runtime.graph_runtime.context).research_act({
        "user_id": "alice",
        "research_messages": [],
        "research_outputs": [],
        "research_tool_calls": 0,
        "pending_tool_calls": [{
            "id": "write-1", "name": "create_learning_reminder",
            "arguments": {"message": "复习", "run_at": "2099-01-01T10:00:00+08:00"},
        }],
    })
    assert result["research_outputs"][0]["rejected"] is True
    assert runtime.database.list_reminders("alice") == []


def test_invalid_citations_fall_back_to_actual_evidence(runtime):
    from app.graph.nodes.workflow import WorkflowNodes

    state = {
        "question": "解释 Agent Loop",
        "intent": "deep_research",
        "draft_answer": "模型记忆中的说法 [W9]",
        "retrieval_hits": [{"content": "Observation 反馈工具结果", "filename": "a.md"}],
        "web_results": [],
    }
    result = WorkflowNodes(runtime.graph_runtime.context).reflect(state)
    assert "[W9]" not in result["final_answer"]
    assert "Observation" in result["final_answer"]
    assert result["reflection"]["fallback"] == "evidence_only"


def test_uploaded_filename_forces_private_rag_over_llm_web_route(runtime):
    from app.services.agent_service import AgentService

    runtime.database.add_document(
        "alice", "宇宙尽头的无聊战争.pdf", "application/pdf",
        [{"content": "林迟因为一次让座导致影子越过宇宙边界，两个宇宙围绕影子归属爆发了荒诞战争。", "section": "第一章"}],
    )
    runtime.llm.complete_json = lambda *args, **kwargs: {"intent": "web_search"}
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="book-thread",
        question="能看到《宇宙尽头的无聊战争》吗，它讲什么？",
    ))
    route = next(item for item in events if item["event"] == "route")
    assert route["data"]["intent"] == "knowledge_qa"
    assert route["data"]["matched_document"] == "宇宙尽头的无聊战争.pdf"
    assert any(item["event"] == "retrieval" for item in events)
    assert not any(item["event"] == "tool_call" for item in events)


def test_uploaded_document_can_escalate_to_web_when_local_evidence_is_weak(runtime):
    from app.tools.web_search import WebSearchResult

    runtime.database.add_document(
        "alice", "专题报告.pdf", "application/pdf",
        [{"content": "专题报告只有一段不完整的背景资料。", "section": "背景"}],
    )
    runtime.tools.web.settings = replace(runtime.settings, tavily_api_key="fake")
    runtime.tools.web.search = lambda query, max_results=None: WebSearchResult(results=[{
        "title": "补充来源", "url": "https://example.com/supplement",
        "content": "外部公开资料补充了缺失信息。", "score": 0.9, "source": "tavily",
    }])
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="document-web-supplement",
        question="《专题报告》讲了什么，还缺哪些公开信息？",
    ))
    route = next(item for item in events if item["event"] == "route")
    decisions = [item["data"]["action"] for item in events if item["event"] == "evidence_decision"]
    assert route["data"]["intent"] == "knowledge_qa"
    assert route["data"]["retrieval_policy"] == "auto"
    assert decisions == ["rewrite", "web"]
    assert "https://example.com/supplement" in events[-1]["data"]["answer"]


def test_weak_local_evidence_escalates_to_optional_web_tool(runtime):
    from app.tools.web_search import WebSearchResult

    runtime.tools.web.settings = replace(runtime.settings, tavily_api_key="fake")
    runtime.tools.web.search = lambda query, max_results=None: WebSearchResult(results=[{
        "title": "Current source", "url": "https://example.com/current",
        "content": "Fresh public evidence", "score": 0.9, "source": "tavily",
    }])
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="optional-web",
        question="根据资料解释这个主题有什么公开进展？",
    ))
    names = [item["event"] for item in events]
    decisions = [item["data"]["action"] for item in events if item["event"] == "evidence_decision"]
    assert decisions == ["rewrite", "web"]
    assert "tool_call" in names
    assert "https://example.com/current" in events[-1]["data"]["answer"]


def test_good_local_evidence_does_not_call_available_web(runtime):
    runtime.database.add_document(
        "alice", "local.md", "text/markdown",
        [
            {"content": "RRF 使用排名倒数融合向量检索和关键词检索。", "section": "融合"},
            {"content": "混合检索可以同时利用语义召回与精确关键词召回。", "section": "召回"},
        ],
    )
    runtime.tools.web.settings = replace(runtime.settings, tavily_api_key="fake")
    called = []
    runtime.tools.web.search = lambda *args, **kwargs: called.append(True)
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="local-good",
        question="根据资料解释 RRF 和混合检索",
    ))
    decisions = [item["data"]["action"] for item in events if item["event"] == "evidence_decision"]
    assert decisions == ["generate"]
    assert called == []


def test_local_only_policy_never_calls_web(runtime):
    runtime.database.add_document(
        "alice", "sparse.md", "text/markdown",
        [{"content": "只有一个很短的本地证据。", "section": "Local"}],
    )
    runtime.tools.web.settings = replace(runtime.settings, tavily_api_key="fake")
    called = []
    runtime.tools.web.search = lambda *args, **kwargs: called.append(True)
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="local-only",
        question="只根据资料解释这个本地证据，不要联网",
    ))
    assert called == []
    assert all(item["event"] != "tool_call" for item in events)


def test_reflection_cannot_remove_required_citations(runtime):
    from dataclasses import replace
    from app.graph.nodes.workflow import WorkflowNodes

    runtime.llm.settings = replace(runtime.llm.settings, llm_api_key="fake")
    runtime.llm.complete_json = lambda *args, **kwargs: {
        "passed": True, "issues": [], "revised_answer": "改写后没有引用",
    }
    result = WorkflowNodes(runtime.graph_runtime.context).reflect({
        "question": "解释 Observation", "intent": "knowledge_qa",
        "draft_answer": "Observation 反馈工具结果 [S1]",
        "retrieval_hits": [{"content": "Observation 反馈工具结果", "filename": "a.md"}],
        "web_results": [],
    })
    assert "[S1]" in result["final_answer"]
    assert result["reflection"]["fallback"] == "evidence_only"
