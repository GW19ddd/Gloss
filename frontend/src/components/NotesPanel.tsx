import { useEffect, useMemo, type MouseEvent as ReactMouseEvent } from "react";
import type { NoteEvidence } from "../api/client";
import { useAiTask } from "../api/aiTasks";
import { useStore } from "../store";
import { AgentTaskCard } from "./AgentTaskCard";
import { Markdown } from "./Markdown";

/**
 * AI-generated Deep Paper Note. Every key claim is tagged [E1], [E2]… and each
 * tag jumps to the verbatim sentence in the PDF. Personal (hand-written) notes
 * live in PersonalNotesPanel.
 */
export function NotesPanel() {
  const current = useStore((state) => state.current);
  const outputLanguage = useStore((state) => state.outputLanguage);
  const uiLang = useStore((state) => state.uiLang);
  const flashLocate = useStore((state) => state.flashLocate);
  const notify = useStore((state) => state.notify);
  const T = uiLang === "zh"
    ? {
        run: "生成 Deep Paper Note",
        regenerate: "↻ 重新生成",
        copy: "⧉ 复制",
        download: "⬇ 下载 .md",
        evidence: "原文证据（点击跳转）",
        jump: "跳转到原文对应位置",
        unlocated: "这句没能在 PDF 里定位到",
        missing: "这句没能在 PDF 里定位到",
      }
    : {
        run: "Generate Deep Paper Note",
        regenerate: "↻ Regenerate",
        copy: "⧉ Copy",
        download: "⬇ Download .md",
        evidence: "Evidence (click to jump)",
        jump: "Jump to the original passage",
        unlocated: "Not located in the PDF",
        missing: "Could not locate this quote in the PDF",
      };
  const key = current ? `notes:${current.id}:${outputLanguage}` : null;
  const { task, running, error, start, restore, cancel } = useAiTask(key);
  useEffect(() => {
    if (!current) return;
    void restore({
      feature_id: "core.notes",
      paper_id: current.id,
      language: outputLanguage,
    });
  }, [key]);
  const raw = task?.result as string | { markdown?: string; evidence?: NoteEvidence[] } | null | undefined;
  const markdown = typeof raw === "string" ? raw : raw?.markdown || "";
  // Notes generated before evidence existed are a bare markdown string.
  const evidence: NoteEvidence[] = (typeof raw === "string" ? [] : raw?.evidence) || [];
  const run = (refresh = false) => {
    if (!current) return;
    void start({
      feature_id: "core.notes",
      paper_id: current.id,
      refresh,
      language: outputLanguage,
    });
  };

  /** Scroll the PDF to `id`'s quote and flash it. */
  function jump(id: string) {
    const ev = evidence.find((e) => e.id === id);
    if (!ev) return;
    if (ev.page == null || !ev.rects?.length) {
      notify(T.missing);
      return;
    }
    flashLocate(ev.page, ev.rects);
  }

  /** Click delegation: Markdown is raw HTML, so listen on the wrapper. */
  function onDocClick(e: ReactMouseEvent<HTMLDivElement>) {
    const el = (e.target as HTMLElement).closest("[data-ev]");
    if (!el) return;
    e.preventDefault();
    jump(el.getAttribute("data-ev") || "");
  }

  // Turn [E1] markers into clickable pills (marked would leave them as plain text).
  const doc = useMemo(
    () => markdown.replace(/\[(E\d+)\]/g, (_m, id) => `<a class="ev-ref" data-ev="${id}">${id}</a>`),
    [markdown],
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown);
    } catch {
      /* Clipboard access may be unavailable in a restricted webview. */
    }
  }

  function download() {
    const trail = evidence.length
      ? "\n\n## Evidence\n\n" +
        evidence
          .map((e) => `- **[${e.id}]** (p${(e.page ?? 0) + 1}): ${e.quote}${e.why ? ` — ${e.why}` : ""}`)
          .join("\n")
      : "";
    const name = `${(current?.title || "deep-paper-note").slice(0, 60)}.md`;
    const blob = new Blob([markdown + trail], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={() => run(!!markdown)} disabled={running || !current}>
          {markdown ? T.regenerate : T.run}
        </button>
        <button onClick={copy} disabled={running || !markdown}>{T.copy}</button>
        <button onClick={download} disabled={running || !markdown}>{T.download}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {task && (running || task.status === "failed" || task.status === "cancelled") && (
        <AgentTaskCard
          task={task}
          uiLang={uiLang}
          agent={{
            name: "Deep Note Scholar",
            name_zh: "深度笔记学者",
            icon: "📚",
            messages: {
              generating: { en: "Writing the deep paper note", zh: "正在撰写深度论文笔记" },
            },
          }}
          onCancel={running ? () => void cancel() : undefined}
        />
      )}
      {markdown && (
        <div className="notes-doc" onClick={onDocClick}>
          <Markdown text={doc} />
        </div>
      )}
      {evidence.length > 0 && (
        <div className="ev-list">
          <h5>{T.evidence}</h5>
          {evidence.map((ev) => {
            const ok = ev.page != null && ev.rects.length > 0;
            return (
              <div
                key={ev.id}
                className={"ev-item" + (ok ? "" : " disabled")}
                onClick={() => ok && jump(ev.id)}
                title={ok ? T.jump : T.unlocated}
              >
                <span className="ev-badge">{ev.id}</span>
                <span className="ev-quote">
                  {ev.quote}
                  {ev.why && <em className="ev-why"> — {ev.why}</em>}
                </span>
                <span className="ev-page">{ok ? `p${ev.page! + 1}` : "—"}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
