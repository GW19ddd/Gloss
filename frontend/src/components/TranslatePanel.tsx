import { Fragment, useEffect, useState } from "react";
import { api, TransSentence } from "../api/client";
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
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sentences, setSentences] = useState<TransSentence[]>([]);
  const [showOriginal, setShowOriginal] = useState(false);
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(1);

  // Restore already-translated pages on entry / paper switch / language change.
  // Uses the same `lang` as translate so the server cache key lines up.
  useEffect(() => {
    if (!current?.id) {
      setSentences([]);
      return;
    }
    let cancelled = false;
    api
      .getTranslations(current.id, lang)
      .then((r) => {
        if (!cancelled) setSentences(r.sentences);
      })
      .catch(() => {
        if (!cancelled) setSentences([]);
      });
    return () => {
      cancelled = true;
    };
  }, [current?.id, lang]);

  async function translateText(t: string) {
    if (!t.trim()) return;
    setLoading(true);
    setOut("");
    setError("");
    try {
      const r = await api.translateText(t, lang);
      setOut(r.translation);
    } catch (e: any) {
      setError("Error: " + (e.message || e));
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
    setError("");
    try {
      // Translate the requested range (reuses cached sentences server-side),
      // then pull the full translated set so reused + new sentences all show in order.
      await api.translatePages(current.id, start, end, lang);
      const r = await api.getTranslations(current.id, lang);
      setSentences(r.sentences);
      setGoto(start);
    } catch (e: any) {
      setError("Error: " + (e.message || e));
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
        placeholder="Select text to translate, or translate whole pages sentence-by-sentence."
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
        <label className="page-picker" style={{ cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showOriginal}
            onChange={(e) => setShowOriginal(e.target.checked)}
          />
          显示原文 (show original)
        </label>
      </div>

      {loading && <div className="muted">Translating into {lang}…</div>}
      {error && <div className="error">{error}</div>}
      {out && <Markdown text={out} />}

      {sentences.length === 0
        ? !loading && (
            <div className="muted">
              No page translations yet — choose a page range above. Already-translated pages are
              restored automatically.
            </div>
          )
        : (
          <div style={{ marginTop: 8 }}>
            {sentences.map((s, i) => (
              <Fragment key={i}>
                {(i === 0 || s.page !== sentences[i - 1].page) && (
                  <div
                    style={{
                      color: "var(--fg-dim)",
                      fontSize: 11,
                      margin: "10px 0 4px",
                      borderTop: "1px solid var(--border)",
                      paddingTop: 6,
                    }}
                  >
                    Page {s.page + 1}
                  </div>
                )}
                <div style={{ padding: "2px 0", fontSize: 13, lineHeight: 1.5 }}>
                  {showOriginal && (
                    <div className="sbs-orig" style={{ fontSize: 12, marginBottom: 2 }}>
                      {s.original}
                    </div>
                  )}
                  <div className="sbs-trans">{s.translation}</div>
                </div>
              </Fragment>
            ))}
          </div>
        )}
    </div>
  );
}
