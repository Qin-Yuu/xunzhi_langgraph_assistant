"use client";

import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUpRight, Check, ChevronDown, Copy, Search, Sparkles, TriangleAlert } from "lucide-react";
import ExecutionTrace from "./ExecutionTrace";

export default function Message({ message }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  if (message.role === "user") return <div className="user-message"><div>{message.content}{message.search_enabled === false && <small className="offline-message-label">联网搜索已关闭</small>}</div></div>;
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true); setCopyError(false);
      setTimeout(() => setCopied(false), 1800);
    } catch { setCopyError(true); }
  }
  return <article className="assistant-message">
    <div className="answer-heading"><span className="answer-mark"><Sparkles size={15}/></span><strong>寻知</strong><span>搜索问答助手</span></div>
    {!!message.trace?.length && <ExecutionTrace steps={message.trace}/>}
    <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{message.content}</Markdown></div>
    {!!message.sources?.length && <section className="sources" aria-label="搜索来源">
      <div className="section-caption"><Search size={13}/> 搜索来源 <span>{message.sources.length}</span></div>
      <div className="source-grid">{message.sources.map((source, i) => <a className="source-card" key={source.url} href={source.url} target="_blank" rel="noopener noreferrer" title={source.excerpt}>
        <div className="source-top"><span className="source-number">{i + 1}</span><span>{source.domain}</span><ArrowUpRight size={13}/></div>
        <strong>{source.title}</strong><p>{source.excerpt || "打开原始页面查看内容"}</p>
      </a>)}</div>
    </section>}
    {!!message.tools?.length && <details className="tool-details">
      <summary><Search size={13}/><span>工具调用记录</span><small>{message.tools.length} 次调用</small><ChevronDown size={14}/></summary>
      <div className="tool-list">{message.tools.map(tool => <div className="tool-row" key={tool.id}>
        <span className={tool.status === "error" ? "tool-state error" : "tool-state"}>{tool.status === "error" ? <TriangleAlert size={14}/> : <Check size={14}/>}</span>
        <div><strong>{tool.name}</strong>{tool.query && <p>搜索词：{tool.query}</p>}<p className="tool-summary">{tool.summary}</p></div>
      </div>)}</div>
    </details>}
    {!message.tools?.length && <p className="no-tool-note">本条未调用搜索工具</p>}
    <button className="copy-button" onClick={copy} aria-label="复制回答">{copied ? <Check size={14}/> : <Copy size={14}/>} {copied ? "已复制" : copyError ? "复制失败，请手动选择文字" : "复制回答"}</button>
  </article>;
}
