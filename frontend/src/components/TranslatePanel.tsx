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
  const flashLocate = useStore((s) => s.flashLocate);
  const uiLang = useStore((s) => s.uiLang);
  const T = {
    en: {
      placeholder: "Select text to translate, or translate whole pages sentence-by-sentence.",
      translateText: "🌐 Translate text",
      fromPage: "from page",
      toPage: "to page",
      translatePages: "Translate pages",
      showOriginal: "Show original",
      translating: (l: string) => `Translating into ${l}…`,
      page: (n: number) => `Page ${n}`,
      locate: "Click to locate in the PDF",
      empty:
        "No page translations yet — choose a page range above. Already-translated pages are restored automatically.",
    },
    zh: {
      placeholder: "选中文本进行翻译，或按句翻译整页。",
      translateText: "🌐 翻译文本",
      fromPage: "起始页",
      toPage: "结束页",
      translatePages: "翻译页面",
      showOriginal: "显示原文",
      translating: (l: string) => `正在翻译为 ${l}…`,
      page: (n: number) => `第 ${n} 页`,
      locate: "点击在原文 PDF 中定位",
      empty: "尚无页面翻译 — 请在上方选择页码范围。已翻译的页面会自动恢复。",
    },
  }[uiLang];

  const [text, setText] = useState("");
  const [out, setOut] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sentences, setSentences] = useState<TransSentence[]>([]);
  const [showOriginal, setShowOriginal] = useState(false);
  // kept as strings so the inputs can be cleared / select-all-deleted freely
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState("1");

  // Restore already-translated pages on entry / paper switch / language change.
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
    const start = (parseInt(from, 10) || 1) - 1;
    const end = (parseInt(to, 10) || 1) - 1;
    setLoading(true);
    setOut("");
    setError("");
    try {
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

  // Click a translated sentence → briefly highlight the original in the PDF.
  async function locate(s: TransSentence) {
    if (!current) return;
    try {
      const loc = await api.locate(current.id, s.original);
      if (loc.page != null && loc.rects.length) flashLocate(loc.page, loc.rects);
      else setGoto(s.page);
    } catch {
      setGoto(s.page);
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
        placeholder={T.placeholder}
        value={text || selection?.text || ""}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="panel-actions">
        <button onClick={() => translateText(text || selection?.text || "")} disabled={loading}>
          {T.translateText}
        </button>
      </div>
      <div className="panel-actions">
        <button onClick={translateRange} disabled={loading}>
          {T.translatePages}
        </button>
        <span className="page-picker">
          {T.fromPage}{" "}
          <input
            type="number"
            min={1}
            max={current?.n_pages}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />{" "}
          {T.toPage}{" "}
          <input
            type="number"
            min={1}
            max={current?.n_pages}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </span>
        <label className="page-picker" style={{ cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showOriginal}
            onChange={(e) => setShowOriginal(e.target.checked)}
          />
          {T.showOriginal}
        </label>
      </div>

      {loading && <div className="muted">{T.translating(lang)}</div>}
      {error && <div className="error">{error}</div>}
      {out && <Markdown text={out} />}

      {sentences.length === 0
        ? !loading && <div className="muted">{T.empty}</div>
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
                    {T.page(s.page + 1)}
                  </div>
                )}
                <div className="trans-cell clickable" title={T.locate} onClick={() => locate(s)}>
                  {showOriginal && <div className="trans-orig">{s.original}</div>}
                  <div className="trans-zh">{s.translation}</div>
                </div>
              </Fragment>
            ))}
          </div>
        )}
    </div>
  );
}
