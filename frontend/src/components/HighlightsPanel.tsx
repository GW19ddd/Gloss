import { useEffect, useState } from "react";
import { api, type PdfCandidate, type PdfTarget } from "../api/client";
import { useStore } from "../store";

const COLORS = ["#ffd54f", "#a5d6a7", "#90caf9", "#ef9a9a", "#ce93d8"];

// Auto-highlight categories → readable names (the DB stores English keys).
const CATEGORY_LABELS: Record<string, { zh: string; en: string }> = {
  contribution: { zh: "核心贡献", en: "Contribution" },
  method: { zh: "方法", en: "Method" },
  result: { zh: "结果", en: "Result" },
  limitation: { zh: "局限", en: "Limitation" },
  definition: { zh: "定义", en: "Definition" },
  background: { zh: "背景", en: "Background" },
};

export function HighlightsPanel() {
  const current = useStore((s) => s.current);
  const highlights = useStore((s) => s.highlights);
  const drawings = useStore((s) => s.drawings);
  const refresh = useStore((s) => s.refreshHighlights);
  const refreshDrawings = useStore((s) => s.refreshDrawings);
  const syncToPdf = useStore((s) => s.syncHighlightsToPdf);
  const notify = useStore((s) => s.notify);
  const setGoto = useStore((s) => s.setGoto);
  const askAboutText = useStore((s) => s.askAboutText);
  const uiLang = useStore((s) => s.uiLang);
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const [editColor, setEditColor] = useState(COLORS[0]);
  const [target, setTarget] = useState<PdfTarget | null>(null);
  const [targetOpen, setTargetOpen] = useState(false);
  const [targetPath, setTargetPath] = useState("");
  const [candidates, setCandidates] = useState<PdfCandidate[]>([]);
  const [searched, setSearched] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  /** which auto-highlight category group is expanded (null = all collapsed) */
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  const T = {
    en: {
      analyzing: "Analyzing…",
      auto: "✨ Auto-highlight key points",
      empty: "No highlights yet. Auto-highlight, or select text in the PDF and pick a color.",
      sync: "↧ Write into the PDF",
      syncing: "Writing…",
      inPdf: "Embedded in the PDF file",
      yours: "Your highlights",
      autos: (n: number) => `Auto highlights (${n})`,
      addToChat: "Add to chat",
      del: "Delete highlight",
      edit: "Edit color or note",
      save: "Save",
      cancel: "Cancel",
      notePlaceholder: "Your note about this passage…",
      ink: (n: number) => `Ink strokes (${n})`,
      inkStroke: { pencil: "Pencil", pen: "Pen", highlighter: "Highlighter" },
      deleteInk: "Delete stroke",
      target: "Write to",
      original: "the original PDF",
      internalCopy: "Gloss's own copy",
      linkBtn: "🔗 Original file…",
      linkHint: "Absolute path of the PDF in Zotero / on disk",
      use: "Use this file",
      detect: "Find automatically",
      detecting: "Searching…",
      unlink: "Stop using the original",
      linked: (n: number) => `Linked — wrote ${n} highlights into the original`,
      missing: "The linked original is no longer at that path.",
      none: "No match found in Zotero storage. Paste the path above.",
    },
    zh: {
      analyzing: "分析中…",
      auto: "✨ 自动标注要点",
      empty: "尚无标注。可自动标注，或在 PDF 中选中文本并选择颜色。",
      sync: "↧ 写入 PDF 文件",
      syncing: "写入中…",
      inPdf: "已写入 PDF 文件（其他阅读器可见）",
      yours: "你的标注",
      autos: (n: number) => `自动标注 (${n})`,
      addToChat: "添加到会话",
      del: "删除标注",
      edit: "编辑颜色或笔记",
      save: "保存",
      cancel: "取消",
      notePlaceholder: "记录你对这段内容的想法…",
      ink: (n: number) => `画笔标注 (${n})`,
      inkStroke: { pencil: "铅笔", pen: "写字笔", highlighter: "荧光笔" },
      deleteInk: "删除笔迹",
      target: "写入目标",
      original: "原件 PDF",
      internalCopy: "Gloss 内部副本",
      linkBtn: "🔗 关联原件…",
      linkHint: "粘贴 Zotero / 磁盘上该 PDF 的绝对路径",
      use: "使用这个文件",
      detect: "自动查找",
      detecting: "查找中…",
      unlink: "取消关联原件",
      linked: (n: number) => `已关联 — 已把 ${n} 条标注写入原件`,
      missing: "关联的原件已不在该路径。",
      none: "Zotero 存储目录里没找到匹配文件，请手动粘贴路径。",
    },
  }[uiLang];

  useEffect(() => {
    if (!current) return;
    setTarget(null);
    setCandidates([]);
    setTargetPath("");
    api.getPdfTarget(current.id).then(setTarget).catch(() => setTarget(null));
  }, [current?.id]);

  async function linkPath(path: string) {
    if (!current || !path.trim()) return;
    const result = await api.linkPdfTarget(current.id, path.trim());
    setTarget(result.target);
    setTargetPath("");
    setCandidates([]);
    notify(T.linked(result.sync.written));
    await refresh();
  }

  async function unlinkOriginal() {
    if (!current) return;
    setTarget(await api.unlinkPdfTarget(current.id));
    setCandidates([]);
  }

  async function detect() {
    if (!current) return;
    setSearching(true);
    try {
      const result = await api.detectPdfTarget(current.id);
      setCandidates(result.candidates || []);
      setSearched(result.searched || []);
      if (!result.candidates?.length) notify(T.none);
    } finally {
      setSearching(false);
    }
  }

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

  async function syncPdf() {
    if (!current) return;
    setSyncing(true);
    try {
      await syncToPdf();
    } finally {
      setSyncing(false);
    }
  }

  async function del(id: string) {
    await api.deleteHighlight(id);
    await refresh();
  }

  async function saveEdit(id: string) {
    await api.patchHighlight(id, { color: editColor, note: editNote.trim() });
    await refresh();
    setEditing(null);
  }

  async function deleteDrawing(id: string) {
    await api.deleteDrawing(id);
    await refreshDrawings();
  }

  const auto_ = highlights.filter((h) => h.kind === "auto");
  const user_ = highlights.filter((h) => h.kind === "user");

  // Auto highlights grouped by category, so 24 of them don't spill everywhere.
  const autoGroups = (() => {
    const map = new Map<string, typeof auto_>();
    for (const h of auto_) {
      const key = h.category || "other";
      const list = map.get(key) ?? [];
      list.push(h);
      map.set(key, list);
    }
    return [...map.entries()];
  })();

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={auto} disabled={busy}>
          {busy ? T.analyzing : T.auto}
        </button>
        <button onClick={syncPdf} disabled={syncing || highlights.length === 0}>
          {syncing ? T.syncing : T.sync}
        </button>
      </div>

      <div className="hl-target">
        <div className="hl-target-head">
          <span className="hl-page">{T.target}</span>
          {target?.is_original
            ? <span className="hl-pdf">{T.original}</span>
            : <span className="muted">{T.internalCopy}</span>}
          <button className="small" onClick={() => setTargetOpen(!targetOpen)}>{T.linkBtn}</button>
        </div>
        {target?.linked_path && (
          <div className="hl-target-path" title={target.linked_path}>{target.linked_path}</div>
        )}
        {target?.linked_missing && <div className="hl-target-warn">{T.missing}</div>}
        {targetOpen && (
          <div className="hl-target-form">
            <input
              value={targetPath}
              placeholder={T.linkHint}
              onChange={(event) => setTargetPath(event.target.value)}
            />
            <div className="hl-target-actions">
              <button className="small primary" disabled={!targetPath.trim()} onClick={() => linkPath(targetPath)}>
                {T.use}
              </button>
              <button className="small" disabled={searching} onClick={detect}>
                {searching ? T.detecting : T.detect}
              </button>
              {target?.is_original && <button className="small" onClick={unlinkOriginal}>{T.unlink}</button>}
            </div>
            {searched.length > 0 && (
              <div className="hl-searched">
                {uiLang === "zh" ? "已扫描目录：" : "Searched: "}
                {searched.join("; ")}
              </div>
            )}
            {candidates.map((candidate) => (
              <div
                key={candidate.path}
                className="hl-candidate"
                title={candidate.path}
              >
                <span className="hl-candidate-name">{candidate.name}</span>
                <span className="hl-candidate-path">{candidate.path}</span>
                <button
                  className="small primary"
                  onClick={() => linkPath(candidate.path)}
                >
                  {T.use}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {highlights.length === 0 && drawings.length === 0 && <div className="muted">{T.empty}</div>}
      {user_.length > 0 && <h5>{T.yours}</h5>}
      {user_.map((h) => (
        <div className="hl-record" key={h.id}>
          <div className="hl-item">
            <span className="hl-swatch" style={{ background: h.color }} />
            <span className="hl-text" onClick={() => setGoto(h.page)}>
              <span className="hl-page">p{h.page + 1}</span>
              {h.pdf_xref != null && <span className="hl-pdf" title={T.inPdf}>PDF</span>} {h.text.slice(0, 140)}
              {h.note && <em className="hl-note"> — {h.note}</em>}
            </span>
            <button className="hl-ask" title={T.edit} onClick={() => {
              setEditing(h.id);
              setEditNote(h.note || "");
              setEditColor(h.color || COLORS[0]);
            }}>📝</button>
            <button className="hl-ask" title={T.addToChat} onClick={() => askAboutText(h.text)}>💬</button>
            <button className="x" title={T.del} onClick={() => del(h.id)}>×</button>
          </div>
          {editing === h.id && (
            <div className="hl-edit">
              <div className="hl-edit-colors">
                {COLORS.map((color) => <button key={color} className={`hl-dot ${editColor === color ? "selected" : ""}`} style={{ background: color }} onClick={() => setEditColor(color)} />)}
              </div>
              <textarea value={editNote} placeholder={T.notePlaceholder} onChange={(event) => setEditNote(event.target.value)} />
              <div><button className="primary small" onClick={() => saveEdit(h.id)}>{T.save}</button><button className="small" onClick={() => setEditing(null)}>{T.cancel}</button></div>
            </div>
          )}
        </div>
      ))}
      {auto_.length > 0 && <h5>{T.autos(auto_.length)}</h5>}
      {autoGroups.map(([cat, items]) => {
        const open = openGroup === cat;
        const label = CATEGORY_LABELS[cat]?.[uiLang] ?? cat;
        return (
          <div className="hl-group" key={cat}>
            <div
              className="hl-group-head"
              title={cat}
              onClick={() => setOpenGroup(open ? null : cat)}
            >
              <span className="hl-swatch" style={{ background: items[0].color }} />
              <span className="hl-group-name">{label}</span>
              <span className="hl-count">{items.length}</span>
              <span className="hl-chev">{open ? "▾" : "▸"}</span>
            </div>
            {open && items.map((h) => (
              <div className="hl-item" key={h.id}>
                <span className="hl-text" onClick={() => setGoto(h.page)}>
                  <span className="hl-page">p{h.page + 1}</span>
                  {h.pdf_xref != null && <span className="hl-pdf" title={T.inPdf}>PDF</span>} {h.text.slice(0, 140)}
                  {h.note && <em className="hl-note"> — {h.note}</em>}
                </span>
                <button className="hl-ask" title={T.addToChat} onClick={() => askAboutText(h.text)}>💬</button>
                <button className="x" title={T.del} onClick={() => del(h.id)}>×</button>
              </div>
            ))}
          </div>
        );
      })}
      {drawings.length > 0 && <h5>{T.ink(drawings.length)}</h5>}
      {drawings.map((drawing) => (
        <div className="hl-item" key={drawing.id}>
          <span className="hl-swatch ink" style={{ background: drawing.color }} />
          <span className="hl-text" onClick={() => setGoto(drawing.page)}>
            <span className="hl-page">p{drawing.page + 1}</span> {T.inkStroke[drawing.tool || "pen"]}
          </span>
          <button className="x" title={T.deleteInk} onClick={() => deleteDrawing(drawing.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
