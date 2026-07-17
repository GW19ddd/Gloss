import { useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";

export function HighlightsPanel() {
  const current = useStore((s) => s.current);
  const highlights = useStore((s) => s.highlights);
  const refresh = useStore((s) => s.refreshHighlights);
  const setGoto = useStore((s) => s.setGoto);
  const askAboutText = useStore((s) => s.askAboutText);
  const uiLang = useStore((s) => s.uiLang);
  const [busy, setBusy] = useState(false);

  const T = {
    en: {
      analyzing: "Analyzing…",
      auto: "✨ Auto-highlight key points",
      empty: "No highlights yet. Auto-highlight, or select text in the PDF and pick a color.",
      yours: "Your highlights",
      autos: (n: number) => `Auto highlights (${n})`,
      addToChat: "Add to chat",
      del: "Delete highlight",
    },
    zh: {
      analyzing: "分析中…",
      auto: "✨ 自动标注要点",
      empty: "尚无标注。可自动标注，或在 PDF 中选中文本并选择颜色。",
      yours: "你的标注",
      autos: (n: number) => `自动标注 (${n})`,
      addToChat: "添加到会话",
      del: "删除标注",
    },
  }[uiLang];

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
          {busy ? T.analyzing : T.auto}
        </button>
      </div>
      {highlights.length === 0 && <div className="muted">{T.empty}</div>}
      {user_.length > 0 && <h5>{T.yours}</h5>}
      {user_.map((h) => (
        <div className="hl-item" key={h.id}>
          <span className="hl-swatch" style={{ background: h.color }} />
          <span className="hl-text" onClick={() => setGoto(h.page)}>
            <span className="hl-page">p{h.page + 1}</span> {h.text.slice(0, 140)}
            {h.note && <em className="hl-note"> — {h.note}</em>}
          </span>
          <button className="hl-ask" title={T.addToChat} onClick={() => askAboutText(h.text)}>💬</button>
          <button className="x" title={T.del} onClick={() => del(h.id)}>×</button>
        </div>
      ))}
      {auto_.length > 0 && <h5>{T.autos(auto_.length)}</h5>}
      {auto_.map((h) => (
        <div className="hl-item" key={h.id}>
          <span className="hl-swatch" style={{ background: h.color }} title={h.category} />
          <span className="hl-text" onClick={() => setGoto(h.page)}>
            <span className="tag">{h.category}</span>
            <span className="hl-page">p{h.page + 1}</span> {h.text.slice(0, 140)}
          </span>
          <button className="hl-ask" title={T.addToChat} onClick={() => askAboutText(h.text)}>💬</button>
          <button className="x" title={T.del} onClick={() => del(h.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
