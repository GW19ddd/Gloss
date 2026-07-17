import { api } from "../api/client";
import { useOp } from "../api/ops";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

export function NotesPanel() {
  const current = useStore((s) => s.current);
  const uiLang = useStore((s) => s.uiLang);
  const T = uiLang === "zh"
    ? { regenerate: "↻ 重新生成", generating: "生成笔记中…", copy: "⧉ 复制", download: "⬇ 下载 .md" }
    : { regenerate: "↻ Regenerate", generating: "Generating notes…", copy: "⧉ Copy", download: "⬇ Download .md" };

  // detached op; autostart only when this tab is active (panels stay mounted)
  const active = useStore((s) => s.activeTab) === "notes";
  const key = current ? `notes:${current.id}` : null;
  const { data: md = "", loading, error, run } = useOp<string>(
    key,
    () => api.notes(current!.id).then((r) => r.markdown),
    active,
  );
  const regenerate = () => run(() => api.notes(current!.id, true).then((r) => r.markdown), true);

  async function copy() {
    try {
      await navigator.clipboard.writeText(md);
    } catch {
      /* ignore */
    }
  }

  function download() {
    const name = ((current?.title || "notes").slice(0, 60)) + ".md";
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={regenerate} disabled={loading}>
          {loading ? T.generating : T.regenerate}
        </button>
        <button onClick={copy} disabled={loading || !md}>
          {T.copy}
        </button>
        <button onClick={download} disabled={loading || !md}>
          {T.download}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {loading && !md && <div className="muted">{T.generating}</div>}
      {md && <Markdown text={md} />}
    </div>
  );
}
