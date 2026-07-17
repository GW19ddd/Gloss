import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

export function TranslatePanel() {
  const current = useStore((s) => s.current);
  const selection = useStore((s) => s.selection);
  const lang = useStore((s) => s.targetLanguage);
  const action = useStore((s) => s.selectionAction);
  const setGoto = useStore((s) => s.setGoto);

  const [text, setText] = useState("");
  const [out, setOut] = useState("");
  const [loading, setLoading] = useState(false);
  const [pageBlocks, setPageBlocks] = useState<any[] | null>(null);
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(1);

  async function translateText(t: string) {
    if (!t.trim()) return;
    setLoading(true);
    setOut("");
    setPageBlocks(null);
    try {
      const r = await api.translateText(t, lang);
      setOut(r.translation);
    } catch (e: any) {
      setOut("Error: " + (e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function translateRange() {
    if (!current) return;
    const start = from - 1;
    const end = to - 1;
    setLoading(true);
    setOut("");
    setPageBlocks(null);
    try {
      const r = await api.translatePages(current.id, start, end, lang);
      setPageBlocks(r.blocks);
      setGoto(start);
    } catch (e: any) {
      setOut("Error: " + (e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (action?.kind === "translate") {
      setText(action.selection.text);
      translateText(action.selection.text);
    }
  }, [action?.id]);

  return (
    <div className="panel-body">
      <textarea
        className="sel-input"
        placeholder="Select text to translate, or translate a whole page side-by-side."
        value={text || selection?.text || ""}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="panel-actions">
        <button onClick={() => translateText(text || selection?.text || "")} disabled={loading}>
          🌐 Translate text
        </button>
        <span className="page-picker">
          from page{" "}
          <input
            type="number"
            min={1}
            max={current?.n_pages}
            value={from}
            onChange={(e) => setFrom(parseInt(e.target.value, 10) || 1)}
          />{" "}
          to page{" "}
          <input
            type="number"
            min={1}
            max={current?.n_pages}
            value={to}
            onChange={(e) => setTo(parseInt(e.target.value, 10) || 1)}
          />
          <button onClick={translateRange} disabled={loading}>
            Translate pages
          </button>
        </span>
      </div>
      {loading && <div className="muted">Translating into {lang}…</div>}
      {out && <Markdown text={out} />}
      {pageBlocks && (
        <div className="sidebyside">
          {pageBlocks.map((b, i) => (
            <Fragment key={i}>
              {(i === 0 || b.page !== pageBlocks[i - 1].page) && (
                <div className="sbs-page" style={{ color: "var(--fg-dim)", fontSize: 11, margin: "8px 0 4px" }}>
                  Page {b.page + 1}
                </div>
              )}
              <div className="sbs-row">
                <div className="sbs-orig">{b.original}</div>
                <div className="sbs-trans">{b.translation}</div>
              </div>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
