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
          <h4>TL;DR</h4>
          <Markdown text={sum.tldr} />
          <div className="grid2">
            <div><h5>Problem</h5><Markdown text={sum.problem} /></div>
            <div><h5>Method</h5><Markdown text={sum.method} /></div>
          </div>
          <h5>Results</h5>
          <Markdown text={sum.results} />
          {sum.contributions?.length > 0 && (
            <>
              <h5>Contributions</h5>
              <ul>{sum.contributions.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
          {sum.key_points?.length > 0 && (
            <>
              <h5>5-minute key points</h5>
              <ul>{sum.key_points.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
          {sum.limitations?.length > 0 && (
            <>
              <h5>Limitations</h5>
              <ul>{sum.limitations.map((c, i) => <li key={i}><Markdown text={c} /></li>)}</ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
