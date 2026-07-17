import { api, Summary } from "../api/client";
import { useOp } from "../api/ops";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

export function SummaryPanel() {
  const current = useStore((s) => s.current);
  const outputLanguage = useStore((s) => s.outputLanguage);
  const uiLang = useStore((s) => s.uiLang);
  const T =
    uiLang === "zh"
      ? { regenerate: "↻ 重新生成", summarizing: "生成摘要中…", reading: "正在阅读论文…" }
      : { regenerate: "↻ Regenerate", summarizing: "Summarizing…", reading: "Reading the paper…" };

  // detached op; autostart only when this tab is active (panels stay mounted)
  const active = useStore((s) => s.activeTab) === "summary";
  const key = current ? `summary:${current.id}:${outputLanguage}` : null;
  const { data: sum, loading, error, run } = useOp<Summary>(
    key,
    () => api.summarize(current!.id, { language: outputLanguage }),
    active,
  );
  const regenerate = () =>
    run(() => api.summarize(current!.id, { refresh: true, language: outputLanguage }), true);

  const zh = uiLang === "zh";
  const L = zh
    ? { tldr: "速览", problem: "问题", method: "方法", results: "结果", contributions: "创新点", key: "5 分钟速读", limits: "局限" }
    : { tldr: "TL;DR", problem: "Problem", method: "Method", results: "Results", contributions: "Contributions", key: "5-minute key points", limits: "Limitations" };

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={regenerate} disabled={loading}>
          {loading ? T.summarizing : T.regenerate}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {loading && !sum && <div className="muted">{T.reading}</div>}
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
