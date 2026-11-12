import { useEffect, useMemo, useState } from "react";
import { api, type NoteEvidence, type ZoteroCandidate } from "../api/client";
import { useAiTask } from "../api/aiTasks";
import { useStore } from "../store";
import { renderWithMath } from "./Markdown";

type Layout = "full" | "brief" | "evidence";
type PdfTargetChoice = "copy" | "auto" | "original";

const BRIEF_HEADINGS = [
  "一句话概述", "创新点", "主要结果", "局限与不足",
  "overview", "contribution", "result", "limitation",
];

/**
 * Every way out of Gloss in one place. The note itself is generated in the
 * Notes tab; this only decides what shape it leaves in.
 */
export function ExportPanel() {
  const current = useStore((state) => state.current);
  const outputLanguage = useStore((state) => state.outputLanguage);
  const uiLang = useStore((state) => state.uiLang);
  const notify = useStore((state) => state.notify);
  const refreshPdfAnnotations = useStore((state) => state.refreshPdfAnnotations);
  const pageLabels = useStore((state) => state.pages?.page_labels);

  /** The number printed on the page, so an export reads like the paper. */
  const label = (page: number | null) =>
    (page != null && pageLabels?.[page]) || String((page ?? 0) + 1);

  const key = current ? `notes:${current.id}:${outputLanguage}` : null;
  const { task, restore } = useAiTask(key);
  useEffect(() => {
    if (!current) return;
    void restore({
      feature_id: "core.notes",
      paper_id: current.id,
      language: outputLanguage,
    });
  }, [key]);

  const raw = task?.result as
    | { markdown?: string; evidence?: NoteEvidence[]; edited?: string | null }
    | null
    | undefined;
  const draft = raw?.markdown || "";
  const evidence = raw?.evidence || [];
  // What the reader is actually looking at: their edit when they have one.
  const markdown = raw?.edited || draft;

  const [layout, setLayout] = useState<Layout>("full");
  const [zoteroMode, setZoteroMode] = useState<"create" | "update">("create");
  const [pdfTarget, setPdfTarget] = useState<PdfTargetChoice>("copy");
  const [zNoteKey, setZNoteKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "zotero" | "pdf">("");
  const [zCands, setZCands] = useState<ZoteroCandidate[]>([]);
  const [zPicking, setZPicking] = useState(false);

  useEffect(() => {
    if (!current) return;
    let alive = true;
    api.zoteroLink(current.id)
      .then((res) => {
        if (!alive) return;
        setZNoteKey(res.link?.note_key || null);
        setZoteroMode(res.link?.note_key ? "update" : "create");
      })
      .catch(() => { /* Zotero may be off; the export itself reports that. */ });
    return () => {
      alive = false;
    };
  }, [current?.id]);

  const evidenceTrail = useMemo(
    () => evidence.length
      ? "\n\n## Evidence\n\n" + evidence
        .map((e) => `- **[${e.id}]** (p${label(e.page ?? null)}): ${e.quote}${e.why ? ` — ${e.why}` : ""}`)
        .join("\n")
      : "",
    [evidence],
  );

  /** "Brief" keeps the sections a reader skims; anything else stays complete. */
  const body = useMemo(() => {
    if (layout === "evidence") return "";
    if (layout === "full") return markdown;
    const kept: string[] = [];
    let take = false;
    for (const line of markdown.split("\n")) {
      const heading = /^#{1,6}\s+(.*)$/.exec(line);
      if (heading) {
        take = BRIEF_HEADINGS.some((word) => heading[1].toLowerCase().includes(word.toLowerCase()));
        if (take) kept.push(line);
        continue;
      }
      if (take) kept.push(line);
    }
    return kept.length ? kept.join("\n").trim() : markdown;
  }, [layout, markdown]);

  const exported = useMemo(() => {
    if (layout === "evidence") {
      return [
        `# ${current?.title || "Evidence"}`,
        "",
        ...evidence.map(
          (e) => `- **[${e.id}]** (p${label(e.page ?? null)})${e.exact === false ? " · 定位为近似" : ""}: ${e.quote}${e.why ? ` — ${e.why}` : ""}`,
        ),
      ].join("\n");
    }
    return body + evidenceTrail;
  }, [layout, body, evidenceTrail, evidence, current?.title]);

  const T = uiLang === "zh"
    ? {
        title: "导出",
        empty: "还没有可导出的笔记。到「笔记 → AI 笔记」生成后再回来。",
        layout: "导出布局",
        full: "完整笔记（含证据表）",
        brief: "仅要点（概述 / 创新 / 结果 / 局限）",
        evidenceOnly: "仅证据清单（编号 · 页码 · 原文）",
        language: "输出语言",
        copy: "⧉ 复制 Markdown",
        copied: "已复制到剪贴板",
        copyFail: "复制失败，请改用下载",
        download: "⬇ 下载 .md",
        zotero: "Zotero",
        zCreate: "新建笔记",
        zUpdate: "更新已有笔记",
        zUpdateOff: "还没有导出过，没有可更新的笔记",
        zExporting: "正在导出…",
        zWritten: "已在 Zotero 写入笔记",
        zUpdated: "已更新 Zotero 中已有的笔记",
        pdf: "PDF 回写",
        pdfCopy: "写入 Gloss 副本（默认，不动原件）",
        pdfOriginal: "写入链接的原件 PDF",
        pdfWriting: "正在写入…",
        pdfWritten: "条证据批注已写入",
        pick: "选择要写入的 Zotero 条目与 PDF：",
      }
    : {
        title: "Export",
        empty: "Nothing to export yet. Generate the note in Notes → AI Note first.",
        layout: "Layout",
        full: "Full note (with evidence table)",
        brief: "Key points only (overview / contributions / results / limits)",
        evidenceOnly: "Evidence list only (id · page · quote)",
        language: "Language",
        copy: "⧉ Copy Markdown",
        copied: "Copied to clipboard",
        copyFail: "Copy failed, use download instead",
        download: "⬇ Download .md",
        zotero: "Zotero",
        zCreate: "Create a new note",
        zUpdate: "Update the existing note",
        zUpdateOff: "Never exported before, so there is no note to update",
        zExporting: "Exporting…",
        zWritten: "Note written to Zotero",
        zUpdated: "The note exported earlier was updated",
        pdf: "Write to PDF",
        pdfCopy: "Write Gloss's own copy (default; the original is untouched)",
        pdfOriginal: "Write the linked original PDF",
        pdfWriting: "Writing…",
        pdfWritten: "evidence annotations written",
        pick: "Pick the Zotero item and PDF to write to:",
      };

  async function copy() {
    try {
      await navigator.clipboard.writeText(exported);
      notify(T.copied);
    } catch {
      notify(T.copyFail);
    }
  }

  function download() {
    const name = `${(current?.title || "gloss-note").slice(0, 60)}.md`;
    const blob = new Blob([exported], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  async function pushToZotero(itemKey: string, attachmentKey: string) {
    if (!current) return;
    setBusy("zotero");
    try {
      const res = await api.zoteroExport(current.id, {
        html: renderWithMath(exported),
        evidence,
        item_key: itemKey,
        attachment_key: attachmentKey,
        // Only ever overwrite when the reader asked for it: creating a second
        // note is annoying, silently replacing their work is worse.
        note_key: zoteroMode === "update" ? (zNoteKey || undefined) : undefined,
      });
      setZNoteKey(res.note_key || null);
      setZPicking(false);
      notify(res.note_updated ? T.zUpdated : T.zWritten);
    } catch (error) {
      notify(String(error));
    } finally {
      setBusy("");
    }
  }

  async function exportToZotero() {
    if (!current || !exported) return;
    setBusy("zotero");
    try {
      const lk = await api.zoteroLink(current.id);
      if (!lk.status.running) {
        notify(lk.status.hint || "Zotero is not running");
        setBusy("");
        return;
      }
      if (lk.link.item_key && lk.link.attachment_key) {
        await pushToZotero(lk.link.item_key, lk.link.attachment_key);
        return;
      }
      const match = await api.zoteroMatch(current.id);
      setZCands(match.candidates);
      setZPicking(true);
      setBusy("");
    } catch (error) {
      notify(String(error));
      setBusy("");
    }
  }

  async function writeToPdf() {
    if (!current || !evidence.length) return;
    setBusy("pdf");
    try {
      const res = await api.evidenceToPdf(current.id, evidence, pdfTarget, "original");
      notify(`${res.written} ${T.pdfWritten}`);
      await refreshPdfAnnotations();
    } catch (error) {
      notify(String(error));
    } finally {
      setBusy("");
    }
  }

  if (!markdown && !evidence.length) {
    return (
      <div className="panel-body">
        <div className="hint">{T.empty}</div>
      </div>
    );
  }

  return (
    <div className="panel-body">
      <div className="export-group">
        <div className="export-row">
          <label>{T.layout}</label>
          <select value={layout} onChange={(event) => setLayout(event.target.value as Layout)}>
            <option value="full">{T.full}</option>
            <option value="brief">{T.brief}</option>
            <option value="evidence">{T.evidenceOnly}</option>
          </select>
        </div>
        <div className="export-row">
          <label>{T.language}</label>
          <input value={outputLanguage} readOnly title={uiLang === "zh" ? "在「工具 → 设置」里修改输出语言" : "Change it in Tools → Settings"} />
        </div>
      </div>

      <div className="export-group">
        <div className="export-head">{uiLang === "zh" ? "文件" : "File"}</div>
        <div className="export-actions">
          <button onClick={() => void copy()} disabled={!exported}>{T.copy}</button>
          <button onClick={download} disabled={!exported}>{T.download}</button>
        </div>
      </div>

      <div className="export-group">
        <div className="export-head">{T.zotero}</div>
        <div className="export-actions">
          <select
            value={zoteroMode}
            onChange={(event) => setZoteroMode(event.target.value as "create" | "update")}
            disabled={busy === "zotero"}
          >
            <option value="create">{T.zCreate}</option>
            <option value="update" disabled={!zNoteKey}>{zNoteKey ? T.zUpdate : T.zUpdateOff}</option>
          </select>
          <button onClick={() => void exportToZotero()} disabled={busy === "zotero" || !exported}>
            {busy === "zotero" ? T.zExporting : "↗ Zotero"}
          </button>
        </div>
      </div>

      <div className="export-group">
        <div className="export-head">{T.pdf}</div>
        <div className="export-actions">
          <select
            value={pdfTarget}
            onChange={(event) => setPdfTarget(event.target.value as PdfTargetChoice)}
            disabled={busy === "pdf" || !evidence.length}
          >
            <option value="copy">{T.pdfCopy}</option>
            <option value="original">{T.pdfOriginal}</option>
          </select>
          <button onClick={() => void writeToPdf()} disabled={busy === "pdf" || !evidence.length}>
            {busy === "pdf" ? T.pdfWriting : "↓ PDF"}
          </button>
        </div>
      </div>

      {zPicking && (
        <div className="zotero-picker">
          <h5>{T.pick}</h5>
          {zCands.length === 0 && <div className="hint">{uiLang === "zh" ? "没找到匹配的 Zotero 条目" : "No matching Zotero item"}</div>}
          {zCands.map((candidate) => (
            <div key={candidate.key} className="zotero-cand">
              <div className="zotero-cand-title">
                {candidate.title}
                {candidate.year ? ` (${candidate.year})` : ""}
              </div>
              {candidate.attachments.map((attachment) => (
                <button key={attachment.key} onClick={() => void pushToZotero(candidate.key, attachment.key)}>
                  {attachment.title || attachment.filename}
                </button>
              ))}
            </div>
          ))}
          <button className="zotero-picker-close" onClick={() => setZPicking(false)} aria-label="close">✕</button>
        </div>
      )}
    </div>
  );
}
