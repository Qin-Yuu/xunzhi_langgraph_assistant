"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUp, BookOpen, ChevronRight, CircleHelp, Clock3, Compass, History, LoaderCircle, Menu, MessageSquare, Plus, RefreshCw, Search, Sparkles, X } from "lucide-react";
import HistoryModal from "./HistoryModal";
import Message from "./Message";
import ExecutionTrace from "./ExecutionTrace";

async function api(path, options = {}) {
  let response;
  try { response = await fetch(`/api${path}`, { ...options, headers: { "Content-Type": "application/json" }, cache: "no-store" }); }
  catch { throw new Error("连接失败，请确认后端已启动，然后重试。"); }
  let data;
  try { data = await response.json(); } catch { throw new Error("服务暂时不可用，请确认后端已启动。"); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "提交失败，请检查输入后重试。");
  return data;
}

const prompts = [
  { icon: Search, title: "了解一个新概念", text: "帮我查查 LangGraph 是什么", query: "请搜索 LangGraph 的官方资料，用中文解释它是什么、适合做什么，并给出来源链接。" },
  { icon: Compass, title: "比较不同选择", text: "梳理方案差异与适用场景", query: "请搜索并比较 React 与 Vue 的主要区别，按适用场景整理，并附上官方资料链接。" },
  { icon: BookOpen, title: "带着来源读资料", text: "查找官方文档，提取要点", query: "请搜索 Python asyncio 的官方文档，整理适合初学者的三个核心概念，并附上来源。" },
];

export default function ChatWorkspace() {
  const [sessions, setSessions] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [activity, setActivity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(null);
  const [history, setHistory] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [health, setHealth] = useState(null);
  const [help, setHelp] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const textarea = useRef(null);
  const bottom = useRef(null);
  const busyRef = useRef(false);
  const pendingMessage = useRef(null);
  const selection = useRef(0);
  const closeHistory = useCallback(() => setHistory(false), []);

  function apply(data) { setMessages(data.messages); setRetry(data.retry); setError(data.error || ""); setProcessing(!!data.processing); setActivity(data.activity || null); }
  async function refresh() { const list = await api("/sessions"); setSessions(list); return list; }

  useEffect(() => {
    let cancelled = false;
    const initialSelection = selection.current;
    try { setSearchEnabled(localStorage.getItem("search-assistant-web-search") !== "false"); } catch {}
    (async () => {
      try {
        const status = await api("/health");
        // Create the visitor cookie before fetching the session list.
        const list = await api("/sessions");
        if (cancelled) return;
        setHealth(status); setSessions(list);
        const last = localStorage.getItem("search-assistant-active");
        if (last && list.some(s => s.id === last) && selection.current === initialSelection) {
          const data = await api(`/sessions/${last}`);
          if (!cancelled && selection.current === initialSelection) { setActive(last); apply(data); }
        }
      } catch (e) { if (!cancelled) setError(e.message); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if ((!processing && !busy) || !active || loading) return;
    let stopped = false;
    let timer;
    const expectedSelection = selection.current;
    async function poll() {
      try {
        const data = await api(`/sessions/${active}`);
        if (stopped || expectedSelection !== selection.current) return;
        if (busy) {
          // Never overwrite optimistic messages or a final response with a stale poll.
          if (!busyRef.current) return;
          if (data.activity?.message_id === pendingMessage.current) setActivity(data.activity);
          timer = setTimeout(poll, 1000);
          return;
        }
        if (busyRef.current) return;
        apply(data);
        if (data.processing) timer = setTimeout(poll, 2000);
        else { try { await refresh(); } catch {} }
      } catch (e) {
        if (!stopped) { if (!busy) setError(e.message); timer = setTimeout(poll, 3000); }
      }
    }
    timer = setTimeout(poll, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [active, processing, busy, loading]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy, activity?.steps?.length]);
  useEffect(() => { if (textarea.current) { textarea.current.style.height = "auto"; textarea.current.style.height = Math.min(textarea.current.scrollHeight, 160) + "px"; } }, [input]);

  function newChat() {
    if (busyRef.current) return;
    selection.current++; setLoading(false); setProcessing(false); setActivity(null); setActive(null); setMessages([]); setInput(""); setError(""); setRetry(null); setMobile(false);
    localStorage.removeItem("search-assistant-active"); textarea.current?.focus();
  }
  async function select(id) {
    if (busyRef.current) return;
    const current = ++selection.current;
    setHistory(false); setMobile(false); setLoading(true); setError("");
    try {
      const data = await api(`/sessions/${id}`);
      if (current === selection.current) { setActive(id); apply(data); localStorage.setItem("search-assistant-active", id); }
    } catch (e) { if (current === selection.current) setError(e.message); }
    finally { if (current === selection.current) setLoading(false); }
  }
  async function openHistory() {
    if (busyRef.current) return;
    try { await refresh(); setHistoryError(""); setHistory(true); }
    catch (e) { setHistoryError(e.message); }
  }
  async function send(saved = null) {
    const content = saved?.content || input.trim();
    if (!content || busyRef.current || loading || processing) return;
    busyRef.current = true; setBusy(true); setError("");
    const messageId = saved?.message_id || crypto.randomUUID();
    pendingMessage.current = messageId;
    setActivity(null);
    const allowSearch = saved?.search_enabled ?? searchEnabled;
    let sid = active;
    const before = messages;
    try {
      if (!sid) {
        const created = await api("/sessions", { method: "POST" });
        sid = created.id; setActive(sid); localStorage.setItem("search-assistant-active", sid);
      }
      if (!saved) { setMessages([...before, { id: messageId, role: "user", content, search_enabled: allowSearch }]); setInput(""); }
      const data = await api(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content, message_id: messageId, search_enabled: allowSearch }) });
      apply(data);
      try { await refresh(); } catch { setHistoryError("对话已保存，历史列表暂未更新，可稍后重新打开。"); }
    } catch (e) {
      if (sid) {
        try {
          const data = await api(`/sessions/${sid}`); apply(data);
          // A request rejected before graph execution can be edited and sent again.
          const sentIndex = data.messages.findIndex(m => m.id === messageId);
          const completed = sentIndex >= 0 && data.messages.slice(sentIndex + 1).some(m => m.role === "assistant");
          if (completed && !data.retry) { setError(""); return; }
          if (!data.retry && !data.processing) setInput(content);
        } catch { setMessages(before); setInput(content); }
      } else setInput(content);
      setError(e.message);
    } finally { pendingMessage.current = null; busyRef.current = false; setBusy(false); textarea.current?.focus(); }
  }

  function toggleSearch() {
    const next = !searchEnabled;
    setSearchEnabled(next);
    try { localStorage.setItem("search-assistant-web-search", String(next)); } catch {}
  }

  const title = sessions.find(s => s.id === active)?.title || "新对话";
  const configured = health?.model_configured && health?.search_configured;
  const searchInProgress = [...messages].reverse().find(m => m.role === "user")?.search_enabled ?? searchEnabled;
  return <div className="app-shell">
    {mobile && <button className="sidebar-backdrop" aria-label="关闭侧栏" onClick={() => setMobile(false)}/>}
    <aside className={`sidebar ${mobile ? "mobile-open" : ""}`}>
      <a className="brand" href="/" onClick={e => { e.preventDefault(); newChat(); }}><span className="brand-symbol"><Sparkles size={22}/></span><div><strong>寻知<span>。</span></strong><small>SEARCH ASSISTANT</small></div></a>
      <button className="new-chat" onClick={newChat} disabled={busy}><Plus size={17}/><span>开启新对话</span><span className="button-plus">＋</span></button>
      <button className="history-nav" onClick={openHistory} disabled={busy}><History size={17}/><span>历史对话</span><ChevronRight size={15}/></button>
      <div className="recent-heading"><span>最近的探索</span><span>{sessions.length ? String(sessions.length).padStart(2, "0") : ""}</span></div>
      <nav className="session-list" aria-label="最近对话">{sessions.length ? sessions.slice(0, 15).map(s => <button disabled={busy} key={s.id} className={`session-item ${active === s.id ? "active" : ""}`} onClick={() => select(s.id)} title={s.title}><MessageSquare size={14}/><span>{s.title}</span></button>) : <div className="no-history"><MessageSquare size={22}/><p>你的每一次探索<br/>都会留在这里</p></div>}</nav>
      {historyError && <p className="sidebar-error" role="alert">{historyError}</p>}
      <div className="sidebar-bottom"><div className="saved-note"><span className="small-dot"/><span>历史对话，自动保存</span></div><button className="about-button" onClick={() => setHelp(true)}><CircleHelp size={15}/>使用说明<ArrowUpRightIcon/></button><p>让问题有答案，让答案有出处。</p></div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><div className="topbar-left"><button className="icon-button menu-button" onClick={() => setMobile(true)} aria-label="打开侧栏"><Menu size={20}/></button><span className="workspace-name">搜索问答</span><span className="topbar-slash">/</span><span className="current-title">{active ? title : "新的探索"}</span></div><div className="service-badge"><span className={`status-dot ${configured ? "online" : ""}`}/>{!health ? "正在连接" : configured ? "已连接" : "待配置"}</div></header>
      <div className={`conversation-scroll ${!messages.length ? "is-empty" : ""}`}>
        {loading ? <div className="loading-state"><LoaderCircle className="spin" size={24}/><p>正在读取对话…</p></div> : messages.length ? <div className="message-column">{messages.map((m, i) => <Message key={m.id || i} message={m}/>)}{(busy || processing) && <div className="thinking" role="status"><span className="answer-mark"><Sparkles size={15}/></span><div><strong>正在整理回答</strong><span>{searchInProgress ? "需要外部资料时，助手会调用搜索工具。" : "本条已关闭联网搜索，正在根据已有上下文回答。"}</span></div><span className="thinking-dots">•••</span></div>}{(busy || processing || retry) && <ExecutionTrace steps={activity?.steps || []} live={busy || processing}/>}<div ref={bottom}/></div> : <section className="welcome">
          <div className="welcome-emblem"><Sparkles size={31} strokeWidth={1.5}/><span className="orbit-dot"/></div>
          <p className="eyebrow">A LITTLE CURIOSITY GOES A LONG WAY</p>
          <h1>好问题，值得<span>好好探索。</span></h1>
          <p className="welcome-description">从一个问题开始。查找资料、梳理思路，<br className="mobile-break"/>让每个回答都有迹可循。</p>
          <div className="suggestions">{prompts.map(({ icon: Icon, title, text, query }) => <button className="suggestion" key={title} onClick={() => { setInput(query); textarea.current?.focus(); }}><Icon size={20} strokeWidth={1.5}/><strong>{title}</strong><span>{text}</span><ArrowRight size={15} className="suggestion-arrow"/></button>)}</div>
          <div className="welcome-features"><span><Search size={13}/>联网查找</span><i/><span><MessageSquare size={13}/>连续追问</span><i/><span><Clock3 size={13}/>历史可回看</span></div>
        </section>}
      </div>
      <div className="composer-area"><div className="composer-column">
        {(error || retry) && !busy && <div className="error-banner" role="alert"><span>{processing ? "助手仍在处理上一条消息，完成后会自动更新。" : error || "上次回答尚未完成，可以点击重试继续。"}</span>{retry && !processing && <button onClick={() => send(retry)}><RefreshCw size={13}/>重试</button>}</div>}
        <form className="composer" onSubmit={e => { e.preventDefault(); send(); }}>
          <textarea ref={textarea} value={input} onChange={e => setInput(e.target.value)} placeholder={retry ? "请先重试上一条消息，或开启新对话" : "有什么想了解的？"} maxLength={12000} rows={1} disabled={busy || processing || loading || !!retry} aria-label="输入问题" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
          <div className="composer-toolbar"><div className="search-controls"><button type="button" role="switch" aria-label="联网搜索" aria-checked={searchEnabled} className={`web-search-toggle ${searchEnabled ? "enabled" : ""}`} disabled={busy || processing || loading || !!retry} onClick={toggleSearch} title={searchEnabled ? "开启：模型按需搜索；点击关闭" : "关闭：本条禁止联网搜索；点击开启"}><Search size={13}/><span>联网搜索</span><span className="toggle-track" aria-hidden="true"><span/></span></button><span className="search-mode-hint">{searchEnabled ? "模型按需搜索" : "本条不联网"}</span></div><button className="send-button" type="submit" disabled={!input.trim() || busy || processing || loading || !!retry} aria-label="发送问题">{busy || processing ? <LoaderCircle size={18} className="spin"/> : <ArrowUp size={20}/>}</button></div>
        </form>
        <p className="composer-hint"><span>回答由 AI 生成，重要信息请核对原始来源。</span><span>Enter 发送 · Shift + Enter 换行</span></p>
      </div></div>
    </main>
    {history && <HistoryModal sessions={sessions} active={active} onSelect={select} onClose={closeHistory}/>}
    {help && <div className="modal-overlay" onClick={() => setHelp(false)}><section className="help-modal" role="dialog" aria-modal="true" aria-label="使用说明" onClick={e => e.stopPropagation()}><button className="icon-button help-close" aria-label="关闭说明" onClick={() => setHelp(false)}><X size={20}/></button><Sparkles size={27} className="accent"/><h2>从一个问题开始</h2><p>联网搜索开启时由模型按需搜索，关闭时不调用搜索工具。运行中可查看自动更新的 ReAct 执行步骤，了解模型选择了什么工具、工具返回了什么，以及是否继续调用。回答完成后，步骤会随历史保留；来源卡片和工具摘要仍可查看。</p><p>历史对话保存在本机，浏览器通过访客标识读取自己的记录。清除浏览器 Cookie 或更换浏览器后，不会自动显示原有会话。</p><button className="primary-button" onClick={() => setHelp(false)}>开始探索<ArrowRight size={15}/></button></section></div>}
  </div>;
}

function ArrowUpRightIcon() { return <svg width="13" height="13" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M5 15 15 5M5 5h10v10" stroke="currentColor" strokeWidth="1.5"/></svg>; }
