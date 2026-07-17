import { useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";

export function HighlightsPanel() {
  const current = useStore((s) => s.current);
  const highlights = useStore((s) => s.highlights);
  const refresh = useStore((s) => s.refreshHighlights);
  const setGoto = useStore((s) => s.setGoto);
  const [busy, setBusy] = useState(false);

  async function auto() {
    if (!current) return;
    setBusy(true);
    try {
      await api.autohighlight(current.id);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function del(id: string) {
    await api.deleteHighlight(id);
    await refresh();
  }

  const auto_ = highlights.filter((h) => h.kind === "auto");
  const user_ = highlights.filter((h) => h.kind === "user");

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={auto} disabled={busy}>
          {busy ? "Analyzing…" : "✨ Auto-highlight key points"}
        </button>
      </div>
      {highlights.length === 0 && <div className="muted">No highlights yet. Auto-highlight, or select text in the PDF and pick a color.</div>}
      {user_.length > 0 && <h5>Your highlights</h5>}
      {user_.map((h) => (
        <div className="hl-item" key={h.id}>
          <span className="hl-swatch" style={{ background: h.color }} />
          <span className="hl-text" onClick={() => setGoto(h.page)}>
            <span className="hl-page">p{h.page + 1}</span> {h.text.slice(0, 140)}
            {h.note && <em className="hl-note"> — {h.note}</em>}
          </span>
          <button className="x" onClick={() => del(h.id)}>×</button>
        </div>
      ))}
      {auto_.length > 0 && <h5>Auto highlights ({auto_.length})</h5>}
      {auto_.map((h) => (
        <div className="hl-item" key={h.id}>
          <span className="hl-swatch" style={{ background: h.color }} title={h.category} />
          <span className="hl-text" onClick={() => setGoto(h.page)}>
            <span className="tag">{h.category}</span>
            <span className="hl-page">p{h.page + 1}</span> {h.text.slice(0, 140)}
          </span>
          <button className="x" onClick={() => del(h.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
