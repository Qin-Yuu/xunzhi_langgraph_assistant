"""Exercise the local API with a real graph and SQLite, without paid model calls."""

import asyncio
import importlib.util
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def make_app(path, monkeypatch, *, fail_once=False):
    assert importlib.util.find_spec("react_agent.web") is not None, "The chat API has not been implemented"
    graph_module = importlib.import_module("react_agent.graph")
    from react_agent.web import create_app

    class Model:
        failed = False

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            if fail_once and not self.failed:
                self.failed = True
                raise RuntimeError("sk-private-test-key must not reach the client")
            humans = [m.content for m in messages if isinstance(m, HumanMessage)]
            return AIMessage(content=" / ".join(humans))

    model = Model()
    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: model)
    return create_app(db_path=path, check_credentials=False)


def test_conversation_survives_restart_and_remembers_context(tmp_path, monkeypatch):
    db = tmp_path / "chat.sqlite3"
    with TestClient(make_app(db, monkeypatch)) as client:
        session = client.post("/api/sessions").json()
        sid = session["id"]
        response = client.post(f"/api/sessions/{sid}/messages", json={"content": "我叫小李", "message_id": "turn-1"})
        assert response.status_code == 200
        assert response.json()["messages"][-1]["content"] == "我叫小李"
        cookies = dict(client.cookies)
    with TestClient(make_app(db, monkeypatch)) as client:
        client.cookies.update(cookies)
        history = client.get(f"/api/sessions/{sid}")
        assert [m["role"] for m in history.json()["messages"]] == ["user", "assistant"]
        reply = client.post(f"/api/sessions/{sid}/messages", json={"content": "我叫什么？", "message_id": "turn-2"})
        assert "我叫小李 / 我叫什么？" == reply.json()["messages"][-1]["content"]
        assert len(client.get("/api/sessions").json()) == 1


def test_session_isolation_and_empty_input(tmp_path, monkeypatch):
    app = make_app(tmp_path / "chat.sqlite3", monkeypatch)
    with TestClient(app) as owner:
        sid = owner.post("/api/sessions").json()["id"]
        assert owner.post(f"/api/sessions/{sid}/messages", json={"content": "  ", "message_id": "empty"}).status_code == 422
        with TestClient(app, raise_server_exceptions=False) as stranger:
            # Use a separate cookie jar, while retaining the same running application.
            assert stranger.get(f"/api/sessions/{sid}").status_code == 404
            assert stranger.get("/api/sessions").json() == []


def test_failed_turn_can_be_retried_without_duplicate_messages(tmp_path, monkeypatch):
    with TestClient(make_app(tmp_path / "chat.sqlite3", monkeypatch, fail_once=True)) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = {"content": "你好", "message_id": "same-turn"}
        failed = client.post(f"/api/sessions/{sid}/messages", json=payload)
        assert failed.status_code == 502
        assert "sk-private" not in failed.text
        assert client.get(f"/api/sessions/{sid}").json()["retry"]["message_id"] == "same-turn"
        successful = client.post(f"/api/sessions/{sid}/messages", json=payload)
        assert successful.status_code == 200
        assert len(successful.json()["messages"]) == 2
        # Repeated delivery of a completed request is idempotent.
        assert len(client.post(f"/api/sessions/{sid}/messages", json=payload).json()["messages"]) == 2


def test_tool_records_and_sources_are_projected_per_turn():
    assert importlib.util.find_spec("react_agent.web") is not None, "The chat API has not been implemented"
    from react_agent.web import project_messages

    messages = [
        HumanMessage(content="查资料", id="u1"),
        AIMessage(content="", tool_calls=[{"id": "t1", "name": "search", "args": {"query": "LangGraph"}}]),
        ToolMessage(content=json.dumps({"results": [{"url": "https://example.com/docs", "title": "文档", "content": "摘要"}, {"url": "javascript:alert(1)", "title": "bad"}]}), tool_call_id="t1", name="search"),
        AIMessage(content="找到资料", id="a1"),
        HumanMessage(content="谢谢", id="u2"),
        AIMessage(content="不客气", id="a2"),
    ]
    result = project_messages(messages)
    assert len(result) == 4
    assert result[1]["tools"][0]["query"] == "LangGraph"
    assert result[1]["sources"][0]["url"] == "https://example.com/docs"
    assert len(result[1]["sources"]) == 1
    assert result[3]["sources"] == []


def test_interrupted_turn_has_recovery_even_without_saved_error(tmp_path, monkeypatch):
    db = tmp_path / "chat.sqlite3"
    app = make_app(db, monkeypatch, fail_once=True)
    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = {"content": "保留这条问题", "message_id": "interrupted"}
        assert client.post(f"/api/sessions/{sid}/messages", json=payload).status_code == 502
        # Reproduce a process crash: checkpoint and pending ID exist, no error was saved.
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE sessions SET last_error=NULL WHERE id=?", (sid,))
        state = client.get(f"/api/sessions/{sid}").json()
        assert state["error"], "An interrupted turn needs a visible recovery message"
        assert state["processing"] is False
        assert state["retry"]["message_id"] == "interrupted"
        assert client.post(f"/api/sessions/{sid}/messages", json=payload).status_code == 200


def test_crash_before_first_checkpoint_does_not_block_session(tmp_path, monkeypatch):
    db = tmp_path / "chat.sqlite3"
    with TestClient(make_app(db, monkeypatch)) as client:
        sid = client.post("/api/sessions").json()["id"]
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE sessions SET pending_id='never-checkpointed' WHERE id=?", (sid,))
        response = client.post(f"/api/sessions/{sid}/messages", json={"content": "新的问题", "message_id": "new"})
        assert response.status_code == 200


def test_timeout_keeps_recoverable_checkpoint(tmp_path, monkeypatch):
    from react_agent.web import create_app
    graph_module = importlib.import_module("react_agent.graph")

    class SlowOnce:
        first = True

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            if self.first:
                self.first = False
                await asyncio.sleep(1)
            return AIMessage(content="恢复完成")

    model = SlowOnce()
    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: model)
    with TestClient(create_app(tmp_path / "chat.sqlite3", check_credentials=False, timeout=.05)) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = {"content": "测试超时", "message_id": "slow"}
        assert client.post(f"/api/sessions/{sid}/messages", json=payload).status_code == 504
        assert client.get(f"/api/sessions/{sid}").json()["retry"]["message_id"] == "slow"
        retry = client.post(f"/api/sessions/{sid}/messages", json=payload)
        assert retry.status_code == 200
        assert len(retry.json()["messages"]) == 2


def test_completed_checkpoint_is_not_replayed_after_metadata_crash(tmp_path, monkeypatch):
    db = tmp_path / "chat.sqlite3"
    with TestClient(make_app(db, monkeypatch)) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = {"content": "已经回答的问题", "message_id": "done"}
        assert client.post(f"/api/sessions/{sid}/messages", json=payload).status_code == 200
        # Final checkpoint exists, but the process died before clearing metadata.
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE sessions SET pending_id='done' WHERE id=?", (sid,))
        reply = client.post(f"/api/sessions/{sid}/messages", json=payload)
        assert len(reply.json()["messages"]) == 2
        assert reply.json()["retry"] is None


def test_search_switch_controls_tool_binding_and_is_saved(tmp_path, monkeypatch):
    from react_agent.web import create_app
    graph_module = importlib.import_module("react_agent.graph")
    bindings = []

    class ProbeModel:
        bound = False

        def bind_tools(self, tools):
            self.bound = True
            return self

        async def ainvoke(self, messages):
            bindings.append(self.bound)
            return AIMessage(content="已回答")

    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: ProbeModel())
    with TestClient(create_app(tmp_path / "switch.sqlite3", check_credentials=False)) as client:
        sid = client.post("/api/sessions").json()["id"]
        for index, enabled in enumerate([False, True]):
            result = client.post(f"/api/sessions/{sid}/messages", json={"content": "测试搜索开关", "message_id": f"switch-{index}", "search_enabled": enabled})
            assert result.status_code == 200
            assert bindings[-1] is enabled
            assert result.json()["messages"][-2]["search_enabled"] is enabled
        # An existing message cannot be replayed with a different search policy.
        assert client.post(f"/api/sessions/{sid}/messages", json={"content": "测试搜索开关", "message_id": "switch-0", "search_enabled": True}).status_code == 409


def test_disabled_search_never_constructs_network_client(monkeypatch):
    from types import SimpleNamespace
    tools_module = importlib.import_module("react_agent.tools")
    monkeypatch.setattr(tools_module, "get_runtime", lambda _: SimpleNamespace(context=SimpleNamespace(search_enabled=False, max_search_results=5)))

    def forbidden(**kwargs):
        pytest.fail("A disabled search must not create the Tavily client")

    monkeypatch.setattr(tools_module, "TavilySearch", forbidden)
    result = asyncio.run(tools_module.search("任何问题"))
    assert result["blocked"] is True


def test_failed_turn_preserves_search_switch_on_retry(tmp_path, monkeypatch):
    with TestClient(make_app(tmp_path / "switch.sqlite3", monkeypatch, fail_once=True)) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = {"content": "不联网提问", "message_id": "offline", "search_enabled": False}
        assert client.post(f"/api/sessions/{sid}/messages", json=payload).status_code == 502
        retry = client.get(f"/api/sessions/{sid}").json()["retry"]
        assert retry["search_enabled"] is False
        assert client.post(f"/api/sessions/{sid}/messages", json=retry).status_code == 200
