"use client";

import { useState } from "react";
import { Check, ChevronDown, LoaderCircle, TriangleAlert, Workflow } from "lucide-react";

export default function ExecutionTrace({ steps = [], live = false }) {
  const [open, setOpen] = useState(true);
  return <details className={`execution-trace ${live ? "live-trace" : ""}`} open={open} onToggle={e => setOpen(e.currentTarget.open)}>
    <summary><Workflow size={14}/><strong>ReAct 执行步骤</strong><small>{live ? "运行中 · 自动更新" : `${steps.length} 个步骤`}</small><ChevronDown size={14}/></summary>
    {steps.length ? <ol className="execution-steps">{steps.map((step, index) => <li key={`${index}-${step.kind}`} className={`execution-step ${step.status}`}>
      <span className="step-indicator">{step.status === "running" ? <LoaderCircle size={12} className="spin"/> : step.status === "error" ? <TriangleAlert size={12}/> : <Check size={12}/>}</span>
      <div><div className="step-heading"><strong>{index + 1}. {step.label}</strong><code>{step.node}</code></div><p>{step.detail}</p></div>
    </li>)}</ol> : <p className="trace-waiting">等待服务端执行记录…</p>}
  </details>;
}
