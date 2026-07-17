import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

export function NotesPanel() {
  const current = useStore((s) => s.current);
  const [md, setMd] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load(refresh = false) {
    if (!current) return;
    setLoading(true);
    setErr("");
    try {
      const r = await api.notes(current.id, refresh);
      setMd(r.markdown);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    setMd("");
    load(false);
  }, [current?.id]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(md);
    } catch (e: any) {
      setErr(String(e.message || e));
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
        <button onClick={() => load(true)} disabled={loading}>
          {loading ? "Generating notes…" : "↻ Regenerate"}
        </button>
        <button onClick={copy} disabled={loading || !md}>
          ⧉ Copy
        </button>
        <button onClick={download} disabled={loading || !md}>
          ⬇ Download .md
        </button>
      </div>
      {err && <div className="error">{err}</div>}
      {loading && !md && <div className="muted">Generating notes…</div>}
      {md && <Markdown text={md} />}
    </div>
  );
}
