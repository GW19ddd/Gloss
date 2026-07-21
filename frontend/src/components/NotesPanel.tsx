import { api } from "../api/client";
import { useOp } from "../api/ops";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

/** AI-generated Deep Paper Note. Personal notes live in PersonalNotesPanel. */
export function NotesPanel() {
  const current = useStore((state) => state.current);
  const uiLang = useStore((state) => state.uiLang);
  const active = useStore((state) => state.activeTab) === "deep-note";
  const T = uiLang === "zh"
    ? {
        regenerate: "↻ 重新生成",
        generating: "生成 Deep Paper Note 中…",
        copy: "⧉ 复制",
        download: "⬇ 下载 .md",
      }
    : {
        regenerate: "↻ Regenerate",
        generating: "Generating Deep Paper Note…",
        copy: "⧉ Copy",
        download: "⬇ Download .md",
      };
  const key = current ? `notes:${current.id}` : null;
  const { data: markdown = "", loading, error, run } = useOp<string>(
    key,
    () => api.notes(current!.id).then((response) => response.markdown),
    active,
  );

  const regenerate = () => run(
    () => api.notes(current!.id, true).then((response) => response.markdown),
    true,
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown);
    } catch {
      /* Clipboard access may be unavailable in a restricted webview. */
    }
  }

  function download() {
    const name = `${(current?.title || "deep-paper-note").slice(0, 60)}.md`;
    const blob = new Blob([markdown], { type: "text/markdown" });
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
        <button onClick={regenerate} disabled={loading}>
          {loading ? T.generating : T.regenerate}
        </button>
        <button onClick={copy} disabled={loading || !markdown}>{T.copy}</button>
        <button onClick={download} disabled={loading || !markdown}>{T.download}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {loading && !markdown && <div className="muted">{T.generating}</div>}
      {markdown && <Markdown text={markdown} />}
    </div>
  );
}
