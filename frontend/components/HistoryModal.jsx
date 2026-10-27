"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, MessageSquare, Search, X } from "lucide-react";

export default function HistoryModal({ sessions, active, onSelect, onClose }) {
  const [query, setQuery] = useState("");
  const input = useRef(null);
  const panel = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    input.current?.focus();
    function key(e) {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const focusable = [...panel.current.querySelectorAll("button, input")];
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); previous?.focus(); };
  }, [onClose]);
  const filtered = sessions.filter(s => s.title.toLowerCase().includes(query.toLowerCase()));
  return <div className="modal-overlay" onClick={onClose}><section ref={panel} className="history-modal" role="dialog" aria-modal="true" aria-labelledby="history-title" onClick={e => e.stopPropagation()}>
    <header><div><p className="eyebrow">YOUR EXPLORATIONS</p><h2 id="history-title">历史对话</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭历史记录"><X size={19}/></button></header>
    <label className="history-search"><Search size={17}/><input ref={input} value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索对话标题"/></label>
    <div className="history-results">{filtered.length ? filtered.map(s => <button key={s.id} className={`history-result ${active === s.id ? "selected" : ""}`} onClick={() => onSelect(s.id)}>
      <MessageSquare size={17}/><div><strong>{s.title}</strong><time>{new Date(s.updated_at).toLocaleString("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time></div><ArrowUpRight size={16}/>
    </button>) : <p className="history-empty">{query ? "没有找到匹配的对话" : "从第一个问题开始，历史会自动保存在这里。"}</p>}</div>
    <footer>对话保存在本机，使用当前浏览器可以继续查看。</footer>
  </section></div>;
}
