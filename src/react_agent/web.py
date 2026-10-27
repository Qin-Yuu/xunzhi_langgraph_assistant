"""Local chat API backed by the upstream ReAct graph and SQLite checkpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import aiosqlite
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import StateSnapshot
from pydantic import BaseModel, Field, field_validator

from react_agent.context import Context
from react_agent.graph import build_graph
from react_agent.utils import get_message_text

ROOT = Path(__file__).resolve().parents[2]
COOKIE = "search_assistant_visitor"
logger = logging.getLogger(__name__)


def now() -> str:
    """Return an ISO timestamp in UTC."""
    return datetime.now(UTC).isoformat()


def tool_result_summary(message: BaseMessage) -> tuple[str, str]:
    """Summarize an actual tool response without exposing model reasoning."""
    text = get_message_text(message)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("blocked"):
        return "error", str(payload.get("error", "工具调用被阻止"))
    if isinstance(payload, dict) and (payload.get("error") or payload.get("status") == "error"):
        return "error", str(payload.get("error") or "搜索工具返回错误")[:500]
    if text.lstrip().startswith("{'error':"):
        return "error", text[:500]
    if getattr(message, "status", "success") == "error":
        return "error", text[:500]
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, list):
        titles = [str(item.get("title", "")) for item in results[:2] if isinstance(item, dict)]
        return "completed", f"收到 {len(results)} 条搜索结果" + ("：" + "；".join(titles) if titles else "")
    return "completed", text[:500]


def execution_steps(
    messages: Sequence[BaseMessage], *, running: bool = False, error: str | None = None,
) -> list[dict[str, str]]:
    """Project one turn's public graph decisions, actions and observations in order."""
    steps: list[dict[str, str]] = []
    actions: dict[str | None, dict[str, str]] = {}
    finished = False
    observed = False
    for message in messages:
        if isinstance(message, HumanMessage):
            steps, actions = [], {}
            steps.append({"kind": "input", "node": "__start__", "label": "收到用户问题", "detail": get_message_text(message)[:300], "status": "completed"})
            observed, finished = False, False
        elif isinstance(message, AIMessage):
            tools = message.tool_calls
            steps.append({"kind": "model", "node": "call_model", "label": "模型读取结果并判断下一步" if observed else "模型判断下一步", "detail": "选择调用工具：" + "、".join(call["name"] for call in tools) if tools else "模型选择输出最终回答", "status": "completed"})
            if tools:
                for call in tools:
                    detail = str(call["args"].get("query") or json.dumps(call["args"], ensure_ascii=False))[:500]
                    action = {"kind": "action", "node": "tools", "label": "执行工具：" + call["name"], "detail": detail, "status": "running"}
                    actions[call["id"]] = action
                    steps.append(action)
            else:
                steps.append({"kind": "final", "node": "__end__", "label": "生成最终回答", "detail": "本轮执行结束", "status": "completed"})
                finished = True
        elif isinstance(message, ToolMessage):
            status, summary = tool_result_summary(message)
            if message.tool_call_id in actions:
                actions[message.tool_call_id]["status"] = status
            steps.append({"kind": "observation", "node": "tools → call_model", "label": "收到工具结果" if status != "error" else "工具返回错误", "detail": summary, "status": status})
            observed = True
    if not finished:
        pending_actions = [step for step in actions.values() if step["status"] == "running"]
        if error and not running:
            for step in pending_actions:
                step["status"] = "error"
            steps.append({"kind": "error", "node": "runtime", "label": "执行中断，可重试", "detail": error, "status": "error"})
        elif running and not pending_actions:
            steps.append({"kind": "model", "node": "call_model", "label": "模型读取结果并判断下一步" if observed else "模型判断下一步", "detail": "等待模型节点返回", "status": "running"})
    return steps


def project_messages(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    """Expose user-facing answers, actual tool calls and search sources per turn."""
    output: list[dict[str, Any]] = []
    calls: dict[str | None, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    turn: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            turn = []
        turn.append(message)
        if isinstance(message, HumanMessage):
            calls, sources = {}, {}
            output.append({"id": message.id, "role": "user", "content": get_message_text(message), "search_enabled": message.additional_kwargs.get("search_enabled", True), "sources": [], "tools": []})
        elif isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                calls[call["id"]] = {"id": call["id"], "name": call["name"], "query": call["args"].get("query", ""), "status": "pending", "summary": ""}
        elif isinstance(message, ToolMessage):
            text = get_message_text(message)
            record = calls.setdefault(message.tool_call_id, {"id": message.tool_call_id, "name": message.name or "search", "query": ""})
            result_status, summary = tool_result_summary(message)
            record.update(status="error" if result_status == "error" else "success", summary=summary)
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                payload = {}
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url", "")
                    try:
                        parsed = urlparse(url)
                    except (ValueError, TypeError):
                        continue
                    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
                        sources.setdefault(url, {"url": url, "title": item.get("title") or parsed.hostname, "excerpt": str(item.get("content") or "")[:320], "domain": parsed.hostname})
                if results and result_status != "error":
                    record["summary"] = f"返回 {len(results)} 条搜索结果"
        elif isinstance(message, AIMessage):
            output.append({"id": message.id, "role": "assistant", "content": get_message_text(message), "sources": list(sources.values()), "tools": [dict(c) for c in calls.values()], "trace": execution_steps(turn)})
    return output


class ChatInput(BaseModel):
    """Validate one message and its per-turn search policy."""

    content: str = Field(min_length=1, max_length=12000)
    message_id: str = Field(min_length=1, max_length=100)
    search_enabled: bool = True

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        """Reject whitespace-only questions."""
        if not value.strip():
            raise ValueError("请输入问题")
        return value.strip()


def create_app(
    db_path: str | Path | None = None, *, check_credentials: bool = True, timeout: float = 100,
) -> FastAPI:
    """Create one local API instance with app-lifetime SQLite connections."""
    load_dotenv(ROOT / ".env", override=False)
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    path = Path(db_path or ROOT / "data" / "assistant.sqlite3")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as db, AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=10000")
            await db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, pending_id TEXT, last_error TEXT)")
            await db.commit()
            await saver.setup()
            app.state.db = db
            app.state.graph = build_graph(saver)
            app.state.locks = {}
            yield

    app = FastAPI(title="Search Assistant", lifespan=lifespan)

    @app.middleware("http")
    async def visitor(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in {"http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:8000"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "请求来源不受支持"}, status_code=403)
        owner = request.cookies.get(COOKIE, "")
        try:
            UUID(owner)
        except ValueError:
            owner = str(uuid4())
        request.state.owner = owner
        response = await call_next(request)
        if owner != request.cookies.get(COOKIE):
            response.set_cookie(COOKIE, owner, max_age=31536000, httponly=True, samesite="lax")
        response.headers["Cache-Control"] = "no-store"
        return response

    async def session(request: Request, sid: str) -> dict[str, Any]:
        async with app.state.db.execute("SELECT id, title, created_at, updated_at, pending_id, last_error FROM sessions WHERE id=? AND owner=?", (sid, request.state.owner)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "会话不存在")
        return dict(zip(("id", "title", "created_at", "updated_at", "pending_id", "last_error"), row))

    async def reconcile(meta: dict[str, Any], state: StateSnapshot) -> None:
        """Recover the two crash windows around a graph run's metadata writes."""
        if not meta["pending_id"]:
            return
        messages = state.values.get("messages", [])
        index = next((i for i, m in enumerate(messages) if m.id == meta["pending_id"]), None)
        complete = index is not None and not state.next and any(isinstance(m, AIMessage) and not m.tool_calls for m in messages[index + 1:])
        if index is None or complete:
            await app.state.db.execute("UPDATE sessions SET pending_id=NULL, last_error=NULL WHERE id=? AND pending_id=?", (meta["id"], meta["pending_id"]))
            await app.state.db.commit()
            meta["pending_id"], meta["last_error"] = None, None

    async def detail(request: Request, sid: str) -> dict[str, Any]:
        meta = await session(request, sid)
        lock = app.state.locks.get(sid)
        processing = bool(meta["pending_id"] and lock and lock.locked())
        state = await app.state.graph.aget_state({"configurable": {"thread_id": sid}})
        if not processing:
            await reconcile(meta, state)
        messages = project_messages(state.values.get("messages", []))
        pending = next((m for m in messages if m["id"] == meta["pending_id"]), None)
        error = meta["last_error"]
        if pending and not processing and not error:
            error = "上次回答中断，可以点击重试继续"
        raw = state.values.get("messages", [])
        last_user = next((i for i in range(len(raw) - 1, -1, -1) if isinstance(raw[i], HumanMessage)), None)
        activity = {"message_id": raw[last_user].id, "steps": execution_steps(raw[last_user:], running=processing, error=error)} if last_user is not None else None
        return {"session": {k: meta[k] for k in ("id", "title", "created_at", "updated_at")}, "messages": messages, "error": error, "processing": processing, "activity": activity, "retry": {"message_id": pending["id"], "content": pending["content"], "search_enabled": pending["search_enabled"]} if pending else None}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "model": os.getenv("MODEL", Context().model), "model_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")), "search_configured": bool(os.getenv("TAVILY_API_KEY"))}

    @app.get("/api/sessions")
    async def list_sessions(request: Request) -> list[dict[str, Any]]:
        async with app.state.db.execute("SELECT id, title, created_at, updated_at FROM sessions WHERE owner=? ORDER BY updated_at DESC", (request.state.owner,)) as cursor:
            return [dict(zip(("id", "title", "created_at", "updated_at"), row)) for row in await cursor.fetchall()]

    @app.post("/api/sessions", status_code=201)
    async def new_session(request: Request) -> dict[str, str]:
        sid, stamp = str(uuid4()), now()
        await app.state.db.execute("INSERT INTO sessions (id, owner, title, created_at, updated_at) VALUES (?,?,?,?,?)", (sid, request.state.owner, "新对话", stamp, stamp))
        await app.state.db.commit()
        return {"id": sid, "title": "新对话", "created_at": stamp, "updated_at": stamp}

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str, request: Request) -> dict[str, Any]:
        return await detail(request, sid)

    @app.post("/api/sessions/{sid}/messages")
    async def send(sid: str, body: ChatInput, request: Request) -> dict[str, Any]:
        await session(request, sid)
        lock = app.state.locks.setdefault(sid, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "这段对话正在处理，请稍候")
        async with lock:
            meta = await session(request, sid)
            config = {"configurable": {"thread_id": sid}, "recursion_limit": 16}
            graph = app.state.graph
            state = await graph.aget_state(config)
            existing = state.values.get("messages", [])
            await reconcile(meta, state)
            if meta["pending_id"] and meta["pending_id"] != body.message_id:
                raise HTTPException(409, "上一条消息尚未完成，请先点击重试，或新建对话")
            previous = next((m for m in existing if m.id == body.message_id), None)
            if previous and get_message_text(previous) != body.content:
                raise HTTPException(409, "消息标识已被使用，请刷新页面")
            if previous and previous.additional_kwargs.get("search_enabled", True) != body.search_enabled:
                raise HTTPException(409, "重试时不能改变原消息的联网搜索设置")
            if previous and not meta["pending_id"]:
                return await detail(request, sid)
            model = os.getenv("MODEL", Context().model)
            if check_credentials:
                key = "OPENAI_API_KEY" if model.startswith("openai/") else "ANTHROPIC_API_KEY" if model.startswith("anthropic/") else "FIREWORKS_API_KEY"
                if not os.getenv(key):
                    raise HTTPException(503, "尚未配置模型密钥，请在项目 .env 中填写并重启后端")
            await app.state.db.execute("UPDATE sessions SET title=?, pending_id=?, last_error=NULL, updated_at=? WHERE id=?", (body.content[:28] if meta["title"] == "新对话" else meta["title"], body.message_id, now(), sid))
            await app.state.db.commit()
            search_instruction = "本条允许联网搜索，需要外部资料时使用搜索工具。根据实际工具结果作答，给出可核对的来源链接。搜索失败时明确说明，不要虚构搜索结果。" if body.search_enabled else "本条已关闭联网搜索。请根据已有知识和对话上下文回答，不要调用搜索工具，也不要声称进行了实时查询；需要最新资料时说明无法核实。"
            context = Context(model=model, max_search_results=5, search_enabled=body.search_enabled, system_prompt="你是一个问答助手。默认用中文回答，用户要求其他语言时遵循用户。" + search_instruction + "\n当前时间：{system_time}")
            try:
                # Resume an interrupted checkpoint on retries; never append the same user twice.
                incoming = None if previous and state.next else {"messages": [HumanMessage(content=body.content, id=body.message_id, additional_kwargs={"search_enabled": body.search_enabled})]}
                await asyncio.wait_for(graph.ainvoke(incoming, config, context=context), timeout=timeout)
            except Exception as exc:
                name = type(exc).__name__
                if isinstance(exc, TimeoutError):
                    reason = "请求超时，可以重试这条消息"
                elif "Authentication" in name or "Permission" in name:
                    reason = "模型鉴权失败，请检查 .env 中的密钥和接口权限并重启后端"
                elif "RateLimit" in name:
                    reason = "模型服务暂时限流，请稍后重试"
                elif "NotFound" in name:
                    reason = "模型不存在，请检查 .env 中的模型名称和接口地址"
                else:
                    reason = "本次请求未完成，请检查模型接口或稍后重试"
                logger.warning("Agent request failed: %s", name)
                await app.state.db.execute("UPDATE sessions SET last_error=? WHERE id=?", (reason, sid))
                await app.state.db.commit()
                raise HTTPException(504 if isinstance(exc, TimeoutError) else 502, reason) from None
            await app.state.db.execute("UPDATE sessions SET pending_id=NULL, last_error=NULL, updated_at=? WHERE id=?", (now(), sid))
            await app.state.db.commit()
            return await detail(request, sid)

    return app


app = create_app()
