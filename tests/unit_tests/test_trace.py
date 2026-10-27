"""Verify that visible ReAct steps reflect actual graph messages and progress."""

import asyncio
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_trace_preserves_two_react_iterations_and_final_answer():
    from react_agent.web import project_messages

    messages = [HumanMessage(content="查资料", id="u")]
    for i in (1, 2):
        messages.extend([
            AIMessage(content="", tool_calls=[{"id": f"t{i}", "name": "search", "args": {"query": f"query-{i}"}}]),
            ToolMessage(content=json.dumps({"results": [{"url": f"https://example.com/{i}", "title": "资料"}]}), tool_call_id=f"t{i}", name="search"),
        ])
    messages.append(AIMessage(content="最终回答", id="answer"))
    trace = project_messages(messages)[-1].get("trace", [])
    assert [s["kind"] for s in trace] == ["input", "model", "action", "observation", "model", "action", "observation", "model", "final"]
    assert all(s["status"] == "completed" for s in trace)
    assert "query-1" in trace[2]["detail"]
    assert "query-2" in trace[5]["detail"]


def test_direct_answer_does_not_invent_tool_steps():
    from react_agent.web import execution_steps
    steps = execution_steps([HumanMessage(content="你好", id="u"), AIMessage(content="你好", id="a")])
    assert [s["kind"] for s in steps] == ["input", "model", "final"]


def test_interrupted_progress_does_not_keep_running_status():
    from react_agent.web import execution_steps
    messages = [HumanMessage(content="搜索", id="u"), AIMessage(content="", tool_calls=[{"id": "t", "name": "search", "args": {"query": "q"}}])]
    steps = execution_steps(messages, error="请求超时")
    assert not any(s["status"] == "running" for s in steps)
    assert steps[-1]["kind"] == "error"


def test_error_shaped_search_response_is_not_shown_as_success():
    from react_agent.web import project_messages
    messages = [HumanMessage(content="搜索", id="u"), AIMessage(content="", tool_calls=[{"id": "t", "name": "search", "args": {"query": "q"}}]), ToolMessage(content='{"error":"quota exhausted"}', tool_call_id="t", name="search"), AIMessage(content="搜索失败", id="a")]
    result = project_messages(messages)[-1]
    assert result["tools"][0]["status"] == "error"
    assert result["trace"][2]["status"] == "error"
    assert result["trace"][3]["status"] == "error"


def test_search_exception_payload_is_serializable(monkeypatch):
    from types import SimpleNamespace
    tools_module = importlib.import_module("react_agent.tools")

    class SearchClient:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, args):
            return {"error": RuntimeError("quota exhausted")}

    monkeypatch.setattr(tools_module, "get_runtime", lambda _: SimpleNamespace(context=SimpleNamespace(search_enabled=True, max_search_results=5)))
    monkeypatch.setattr(tools_module, "TavilySearch", SearchClient)
    result = asyncio.run(tools_module.search("q"))
    assert result["status"] == "error"
    assert isinstance(result["error"], str)
    json.dumps(result)


def test_live_progress_is_available_before_post_finishes_and_survives_restart(tmp_path, monkeypatch):
    from react_agent.web import create_app
    graph_module = importlib.import_module("react_agent.graph")
    tools_module = importlib.import_module("react_agent.tools")
    entered, release = threading.Event(), threading.Event()

    class SearchClient:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, args):
            entered.set()
            await asyncio.to_thread(release.wait, 5)
            return {"results": [{"url": "https://example.com", "title": "Example", "content": "实际工具结果"}]}

    class Model:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            if not any(isinstance(m, ToolMessage) for m in messages):
                return AIMessage(content="", tool_calls=[{"id": "live-search", "name": "search", "args": {"query": "测试查询"}}])
            return AIMessage(content="根据工具结果回答")

    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: Model())
    monkeypatch.setattr(tools_module, "TavilySearch", SearchClient)
    db = tmp_path / "trace.sqlite3"
    with TestClient(create_app(db, check_credentials=False)) as client:
        sid = client.post("/api/sessions").json()["id"]
        with ThreadPoolExecutor() as executor:
            future = executor.submit(client.post, f"/api/sessions/{sid}/messages", json={"content": "请搜索", "message_id": "live-user"})
            try:
                assert entered.wait(3), "The graph should have entered the search tool"
                progress = client.get(f"/api/sessions/{sid}").json()
                assert progress["processing"] is True
                assert not future.done()
                assert progress.get("activity", {}).get("message_id") == "live-user"
                assert progress["activity"]["steps"][-1]["kind"] == "action"
                assert progress["activity"]["steps"][-1]["status"] == "running"
            finally:
                release.set()
            result = future.result(timeout=5)
            assert result.status_code == 200
            final_trace = result.json()["messages"][-1]["trace"]
            assert final_trace[-1]["kind"] == "final"
        cookies = dict(client.cookies)
    with TestClient(create_app(db, check_credentials=False)) as client:
        client.cookies.update(cookies)
        assert client.get(f"/api/sessions/{sid}").json()["messages"][-1]["trace"] == final_trace
