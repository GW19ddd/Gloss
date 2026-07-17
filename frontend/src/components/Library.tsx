import { useRef, useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";

export function Library() {
  const papers = useStore((s) => s.papers);
  const openPaper = useStore((s) => s.openPaper);
  const loadPapers = useStore((s) => s.loadPapers);
  const notify = useStore((s) => s.notify);
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
    if (!confirm("Delete this paper?")) return;
    await api.deletePaper(id);
    await loadPapers();
  }

  return (
    <div className="library">
      <div className="lib-hero">
        <h1>🌙 Moonlight</h1>
        <p className="tagline">Your local AI colleague for reading papers — powered by your local Claude.</p>
        <div className="import-row">
          <input
            className="import-input"
            placeholder="arXiv id / URL / DOI  (e.g. 1706.03762)"
            value={importQ}
            onChange={(e) => setImportQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onImport()}
          />
          <button onClick={onImport} disabled={busy}>Import</button>
          <button onClick={() => fileRef.current?.click()} disabled={busy}>Upload PDF</button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => onUpload(e.target.files)}
          />
        </div>
        {busy && <div className="muted">Working…</div>}
      </div>

      <div className="lib-grid">
        {papers.length === 0 && <div className="muted empty">No papers yet — import an arXiv id or upload a PDF.</div>}
        {papers.map((p) => (
          <div className="card" key={p.id} onClick={() => openPaper(p.id)}>
            <div className="card-title">{p.title || "Untitled"}</div>
            <div className="card-auth">{(p.authors || []).slice(0, 4).join(", ")}</div>
            <div className="card-meta">
              <span>{p.n_pages}p</span>
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
