import { useEffect, useState } from "react";
import { api, Summary } from "../api/client";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

// module-scoped cache so re-opening the tab is instant (no re-fetch/regenerate)
const CACHE = new Map<string, Summary>();

export function SummaryPanel() {
  const current = useStore((s) => s.current);
  const outputLanguage = useStore((s) => s.outputLanguage);
  const [sum, setSum] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load(refresh = false) {
    if (!current) return;
    const key = `${current.id}:${outputLanguage}`;
    if (!refresh && CACHE.has(key)) {
      setSum(CACHE.get(key)!);
      return;
    }
    setLoading(true);
    setErr("");
    try {
      const s = await api.summarize(current.id, { refresh, language: outputLanguage });
      CACHE.set(key, s);
      setSum(s);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    const key = current ? `${current.id}:${outputLanguage}` : "";
    setSum(key && CACHE.has(key) ? CACHE.get(key)! : null);
    load(false);
  }, [current?.id, outputLanguage]);

  const zh = outputLanguage.startsWith("中文");
  const L = zh
    ? { tldr: "速览", problem: "问题", method: "方法", results: "结果", contributions: "创新点", key: "5 分钟速读", limits: "局限" }
    : { tldr: "TL;DR", problem: "Problem", method: "Method", results: "Results", contributions: "Contributions", key: "5-minute key points", limits: "Limitations" };

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={() => load(true)} disabled={loading}>
          {loading ? "Summarizing…" : "↻ Regenerate"}
        </button>
      </div>
      {err && <div className="error">{err}</div>}
      {loading && !sum && <div className="muted">Reading the paper…</div>}
      {sum && (
        <div className="summary">
          <h4>{L.tldr}</h4>
          <Markdown text={sum.tldr} />
          <div className="grid2">
            <div><h5>{L.problem}</h5><Markdown text={sum.problem} /></div>
            <div><h5>{L.method}</h5><Markdown text={sum.method} /></div>
          </div>
          <h5>{L.results}</h5>
          <Markdown text={sum.results} />
          {sum.contributions?.length > 0 && (
            <>
              <h5>{L.contributions}</h5>
              <ul>{sum.contributions.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
          {sum.key_points?.length > 0 && (
            <>
              <h5>{L.key}</h5>
              <ul>{sum.key_points.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
          {sum.limitations?.length > 0 && (
            <>
              <h5>{L.limits}</h5>
              <ul>{sum.limitations.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
