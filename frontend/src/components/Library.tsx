import { useRef, useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";
import { Logo } from "./Logo";

export function Library() {
  const papers = useStore((s) => s.papers);
  const openPaper = useStore((s) => s.openPaper);
  const loadPapers = useStore((s) => s.loadPapers);
  const notify = useStore((s) => s.notify);
  const uiLang = useStore((s) => s.uiLang);
  const T = {
    en: {
      tagline: "Annotate your papers with light · a local AI paper-reading companion, powered by your local Claude.",
      placeholder: "arXiv id / URL / DOI  (e.g. 1706.03762)",
      import: "Import",
      upload: "Upload PDF",
      working: "Working…",
      empty: "No papers yet — import an arXiv id or upload a PDF.",
      confirmDelete: "Delete this paper?",
      pages: (n: number) => `${n}p`,
    },
    zh: {
      tagline: "照亮论文的批注 · 本地 AI 论文阅读助手，默认接入本地 Claude。",
      placeholder: "arXiv 编号 / 链接 / DOI  (例如 1706.03762)",
      import: "导入",
      upload: "上传 PDF",
      working: "处理中…",
      empty: "还没有论文 — 导入 arXiv 编号或上传 PDF。",
      confirmDelete: "删除这篇论文？",
      pages: (n: number) => `${n} 页`,
    },
  }[uiLang];
  const [importQ, setImportQ] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) {
        const p = await api.uploadPaper(f);
        notify("Added: " + (p.title || f.name).slice(0, 40));
      }
      await loadPapers();
    } catch (e: any) {
      notify("Upload failed: " + (e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function onImport() {
    if (!importQ.trim()) return;
    setBusy(true);
    try {
      const p = await api.importPaper(importQ.trim());
      setImportQ("");
      await loadPapers();
      notify("Imported: " + (p.title || "").slice(0, 40));
      openPaper(p.id);
    } catch (e: any) {
      notify("Import failed: " + (e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function del(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(T.confirmDelete)) return;
    await api.deletePaper(id);
    await loadPapers();
  }

  return (
    <div className="library">
      <div className="lib-hero">
        <h1 className="hero-title"><Logo size={40} /> Gloss <span className="hero-zh">旁注</span></h1>
        <p className="tagline">{T.tagline}</p>
        <div className="import-row">
          <input
            className="import-input"
            placeholder={T.placeholder}
            value={importQ}
            onChange={(e) => setImportQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onImport()}
          />
          <button onClick={onImport} disabled={busy}>{T.import}</button>
          <button onClick={() => fileRef.current?.click()} disabled={busy}>{T.upload}</button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => onUpload(e.target.files)}
          />
        </div>
        {busy && <div className="muted">{T.working}</div>}
      </div>

      <div className="lib-grid">
        {papers.length === 0 && <div className="muted empty">{T.empty}</div>}
        {papers.map((p) => (
          <div className="card" key={p.id} onClick={() => openPaper(p.id)}>
            <div className="card-title">{p.title || "Untitled"}</div>
            <div className="card-auth">{(p.authors || []).slice(0, 4).join(", ")}</div>
            <div className="card-meta">
              <span>{T.pages(p.n_pages)}</span>
              {p.year && <span>· {p.year}</span>}
              {p.source && <span>· {p.source}</span>}
            </div>
            <button className="card-del" onClick={(e) => del(p.id, e)}>×</button>
          </div>
        ))}
      </div>
    </div>
  );
}
