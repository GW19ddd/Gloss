import { useState } from "react";
import { api, ScholarResult } from "../api/client";
import { useStore } from "../store";

export function ScholarPanel() {
  const current = useStore((s) => s.current);
  const notify = useStore((s) => s.notify);
  const loadPapers = useStore((s) => s.loadPapers);
  const openPaper = useStore((s) => s.openPaper);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<ScholarResult[]>([]);
  const [busy, setBusy] = useState(false);

  async function search() {
    if (!q.trim()) return;
    setBusy(true);
    try {
      const r = await api.scholarSearch(q, 12);
      setResults(r.results);
    } finally {
      setBusy(false);
    }
  }
  async function recommend() {
    if (!current) return;
    setBusy(true);
    try {
      const r = await api.scholarRecommend(current.id, 12);
      setResults(r.results);
    } finally {
      setBusy(false);
    }
  }
  async function importPaper(res: ScholarResult) {
    const query = res.arxiv_id || res.url || res.doi || res.title;
    try {
      const p = await api.importPaper(query);
      await loadPapers();
      notify("Imported: " + (p.title || "").slice(0, 40));
      openPaper(p.id);
    } catch (e: any) {
      notify("Import failed: " + (e.message || e));
    }
  }

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <input
          className="search"
          placeholder="Search papers (Semantic Scholar / arXiv)…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
        />
        <button onClick={search} disabled={busy}>Search</button>
        <button onClick={recommend} disabled={busy || !current} title="Related to this paper">
          ✦ Related
        </button>
      </div>
      {busy && <div className="muted">Searching…</div>}
      {results.map((r, i) => (
        <div className="scholar-item" key={i}>
          <div className="ref-title">
            {r.url ? (
              <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
            ) : (
              r.title
            )}{" "}
            {r.year && <span className="ref-year">({r.year})</span>}
            {r.citations != null && <span className="cites">· {r.citations} cites</span>}
          </div>
          {r.authors?.length > 0 && <div className="ref-auth">{r.authors.slice(0, 5).join(", ")}</div>}
          {r.abstract && <div className="ref-abs">{r.abstract.slice(0, 220)}…</div>}
          {(r.arxiv_id || r.url?.includes("arxiv")) && (
            <button className="small" onClick={() => importPaper(r)}>
              ＋ Import to library
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
