from __future__ import annotations

from dataclasses import replace

from app.graph.nodes.common import route_intent_rule
from app.tools.web_search import TavilyWebSearch


def test_natural_language_routes_web_without_mode_switch():
    assert route_intent_rule("联网查一下 LangGraph 最近有什么更新") == "web_search"
    assert route_intent_rule("联网深入研究 LangGraph 最新进展") == "deep_research"


def test_tavily_adapter_normalizes_results(settings):
    class FakeTavilyClient:
        def search(self, **kwargs):
            assert kwargs["query"] == "LangGraph updates"
            return {
                "answer": "A short summary",
                "results": [{"title": "Release", "url": "https://example.com/release", "content": "New features", "score": 0.91}],
            }

    search = TavilyWebSearch(replace(settings, tavily_api_key="test-key"))
    search._client = FakeTavilyClient()
    result = search.search("LangGraph updates")
    assert result.error == ""
    assert result.answer == "A short summary"
    assert result.results[0]["source"] == "tavily"


def test_tavily_adapter_is_optional(settings):
    result = TavilyWebSearch(settings).search("anything")
    assert result.results == []
    assert "TAVILY_API_KEY" in result.error


def test_agent_web_search_emits_tool_trace(runtime):
    from dataclasses import replace
    from app.services.agent_service import AgentService
    from app.tools.web_search import WebSearchResult

    runtime.tools.web.settings = replace(runtime.settings, tavily_api_key="fake")
    runtime.tools.web.search = lambda query, max_results=None: WebSearchResult(results=[{
        "title": "LangGraph release", "url": "https://example.com/langgraph",
        "content": "A current release note.", "score": 0.9, "source": "tavily",
    }])
    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="web-thread", question="联网查一下 LangGraph 最近有什么更新"
    ))
    names = [item["event"] for item in events]
    assert "tool_call" in names
    assert "tool_result" in names
    assert "https://example.com/langgraph" in events[-1]["data"]["answer"]


def test_native_function_call_messages_are_serialized_for_openai(monkeypatch, settings):
    from dataclasses import replace
    from app.llm.client import ChatClient

    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "done", "tool_calls": []}}]}

    def fake_post(url, json, headers, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    client = ChatClient(replace(settings, llm_api_key="key"))
    result = client.complete_with_tools([
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "search_web", "arguments": {"query": "RAG"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "search_web", "content": "{}"},
    ], [{"type": "function", "function": {"name": "search_web", "parameters": {"type": "object"}}}])
    call = captured["messages"][0]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "search_web"
    assert call["function"]["arguments"] == '{"query": "RAG"}'
    assert result["content"] == "done"


def test_chat_retries_without_unsupported_temperature(monkeypatch, settings):
    from dataclasses import replace
    from app.llm.client import ChatClient

    payloads = []

    class Response:
        def __init__(self, status_code, value):
            self.status_code = status_code
            self.value = value

        def json(self):
            return self.value

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("unexpected failed retry")

    def fake_post(url, json, headers, timeout):
        payloads.append(json)
        if len(payloads) == 1:
            return Response(400, {"error": {"param": "temperature", "message": "unsupported temperature"}})
        return Response(200, {"choices": [{"message": {"content": "兼容成功"}}]})

    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    client = ChatClient(replace(settings, llm_api_key="local"))
    assert client.complete([{"role": "user", "content": "hello"}]) == "兼容成功"
    assert "temperature" in payloads[0]
    assert "temperature" not in payloads[1]
    assert client.complete([{"role": "user", "content": "again"}]) == "兼容成功"
    assert "temperature" not in payloads[2]
