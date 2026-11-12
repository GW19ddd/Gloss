import { useEffect, useState } from "react";
import { useStore } from "../store";
import { api } from "../api/client";

// Left rail: section outline for quick navigation. Resizable + collapsible (App owns width/collapse).
export function Outline({ onCollapse }: { onCollapse?: () => void }) {
  const pages = useStore((s) => s.pages);
  const setGoto = useStore((s) => s.setGoto);
  const uiLang = useStore((s) => s.uiLang);
  const paperId = useStore((s) => s.current?.id);
  const refreshPages = useStore((s) => s.refreshPages);
  const notify = useStore((s) => s.notify);
  const outputLanguage = useStore((s) => s.outputLanguage);
  const T = {
    en: {
      outline: "Outline", collapse: "Collapse outline", none: "No sections detected",
      wrap: "Wrap long titles", fix: "Fix with AI", restore: "Restore raw outline",
      ok: "Outline fixed", fail: "Fix failed",
      toPdf: "Write outline into the PDF's bookmarks",
      toPdfConfirm: "This replaces the bookmarks in the PDF file with the outline below — other PDF readers will show it too. The bookmarks it has now are kept aside and can be restored. Continue?",
      pdfOk: "Outline written into the PDF", pdfFail: "Could not write the PDF",
      undoPdf: "Restore the PDF's original bookmarks",
      pdfUndone: "PDF bookmarks restored",
    },
    zh: {
      outline: "大纲", collapse: "收起大纲", none: "未检测到章节",
      wrap: "长标题换行显示", fix: "AI 修复", restore: "还原大纲",
      ok: "大纲已修复", fail: "修复失败",
      toPdf: "把大纲写进 PDF 书签（目录）",
      toPdfConfirm: "这会用下面的大纲替换 PDF 文件中的书签，其他阅读器打开也会显示新大纲。PDF 原有的书签会被另行保存，随时可以还原。继续吗？",
      pdfOk: "大纲已写入 PDF 书签", pdfFail: "写入 PDF 失败",
      undoPdf: "还原 PDF 原本的书签",
      pdfUndone: "PDF 书签已还原",
    },
  }[uiLang];
  const sections = pages?.sections || [];
  // The outline follows the answer language: switching it shows that language's
  // version (generated on demand when it does not exist yet).
  const langLabel = outputLanguage.startsWith("中文") ? "中文" : "English";
  const written = !!pages?.outline_written;
  // A long title must never widen the rail, so by default it is clipped. Wrapping
  // is opt-in and remembered.
  const [wrap, setWrap] = useState(() => localStorage.getItem("gloss.outlineWrap") === "1");
  const [fixing, setFixing] = useState(false);
  const [writing, setWriting] = useState(false);
  const fixed = !!pages?.outline_fixed;
  useEffect(() => {
    localStorage.setItem("gloss.outlineWrap", wrap ? "1" : "0");
  }, [wrap]);

  async function fixOutline() {
    if (!paperId || fixing) return;
    setFixing(true);
    try {
      await api.fixOutline(paperId, { language: outputLanguage });
      await refreshPages();
      notify(T.ok);
    } catch (e) {
      notify(`${T.fail}: ${e instanceof Error ? e.message : e}`);
    } finally {
      setFixing(false);
    }
  }

  async function restoreOutline() {
    if (!paperId || fixing) return;
    setFixing(true);
    try {
      await api.resetOutline(paperId, outputLanguage);
      await refreshPages();
    } catch (e) {
      notify(`${T.fail}: ${e instanceof Error ? e.message : e}`);
    } finally {
      setFixing(false);
    }
  }

  async function writeToPdf() {
    if (!paperId || writing) return;
    if (!window.confirm(T.toPdfConfirm)) return;
    setWriting(true);
    try {
      const result = await api.writeOutlineToPdf(paperId, outputLanguage);
      await refreshPages();
      notify(`${T.pdfOk} (${result.written})`);
    } catch (e) {
      notify(`${T.pdfFail}: ${e instanceof Error ? e.message : e}`);
    } finally {
      setWriting(false);
    }
  }

  async function restorePdfBookmarks() {
    if (!paperId || writing) return;
    setWriting(true);
    try {
      await api.restorePdfOutline(paperId);
      await refreshPages();
      notify(T.pdfUndone);
    } catch (e) {
      notify(`${T.pdfFail}: ${e instanceof Error ? e.message : e}`);
    } finally {
      setWriting(false);
    }
  }

  return (
    <div className={`outline${wrap ? " wrap" : ""}`}>
      <div className="outline-head">
        <span>{T.outline}</span>
        <span className="outline-head-actions">
          <button
            className="outline-fix"
            title={fixed ? T.restore : `${T.fix} · ${langLabel}`}
            disabled={fixing}
            onClick={fixed ? restoreOutline : fixOutline}
          >
            {fixing ? "…" : fixed ? T.restore : T.fix}
          </button>
          <button
            className={`outline-pdf${written ? " active" : ""}`}
            title={written ? T.undoPdf : `${T.toPdf} · ${langLabel}`}
            disabled={writing || sections.length === 0}
            onClick={written ? restorePdfBookmarks : writeToPdf}
          >
            {writing ? "…" : written ? "↺" : "⇩"}
          </button>
          <button
            className={`outline-wrap${wrap ? " active" : ""}`}
            title={T.wrap}
            onClick={() => setWrap((on) => !on)}
          >
            ⤢
          </button>
          {onCollapse && (
            <button className="outline-collapse" title={T.collapse} onClick={onCollapse}>
              «
            </button>
          )}
        </span>
      </div>
      <div className="outline-list">
        {sections.length === 0 && (
          <div className="muted" style={{ padding: "8px 12px" }}>{T.none}</div>
        )}
        {sections.map((s, i) => (
          <div
            key={i}
            className="outline-item"
            style={{ paddingLeft: 8 + (s.level - 1) * 12 }}
            onClick={() => setGoto(s.page)}
            title={s.title}
          >
            {s.title}
          </div>
        ))}
      </div>
    </div>
  );
}
