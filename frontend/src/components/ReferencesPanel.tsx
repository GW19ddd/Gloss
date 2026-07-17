import { useEffect, useState } from "react";
import { api, Reference } from "../api/client";
import { useStore } from "../store";

function refLink(r: Reference): string {
  if (r.url) return r.url;
  if (r.arxiv_id) return `https://arxiv.org/abs/${r.arxiv_id}`;
  if (r.doi) return `https://doi.org/${r.doi}`;
  const q = encodeURIComponent(r.title || r.raw || "");
  return `https://scholar.google.com/scholar?q=${q}`;
}

export function ReferencesPanel() {
  const current = useStore((s) => s.current);
  const [refs, setRefs] = useState<Reference[]>([]);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!current) return;
    const { references } = await api.getReferences(current.id);
    setRefs(references);
  }
  useEffect(() => {
    setRefs([]);
    load();
  }, [current?.id]);

  async function resolve() {
    if (!current) return;
    setBusy(true);
    try {
      const { references } = await api.resolveReferences(current.id);
      setRefs(references);
    } finally {
      setBusy(false);
    }
  }

  const resolved = refs.filter((r) => r.resolved).length;

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={resolve} disabled={busy}>
          {busy ? "Resolving…" : "🔎 Resolve & enrich references"}
        </button>
        <span className="muted">{refs.length} refs · {resolved} resolved</span>
      </div>
      {refs.length === 0 && <div className="muted">No references parsed for this paper.</div>}
      <ol className="ref-list">
        {refs.map((r) => (
          <li key={r.id}>
            {r.title ? (
              <>
                <div className="ref-title">
                  <a href={refLink(r)} target="_blank" rel="noreferrer">
                    {r.title}
                  </a>{" "}
                  {r.year && <span className="ref-year">({r.year})</span>}
                </div>
                {r.authors?.length > 0 && <div className="ref-auth">{r.authors.slice(0, 6).join(", ")}</div>}
                {r.abstract && <div className="ref-abs">{r.abstract.slice(0, 260)}…</div>}
                {(r.doi || r.arxiv_id) && (
                  <div className="ref-ids">
                    {r.doi && <span>doi:{r.doi}</span>} {r.arxiv_id && <span>arXiv:{r.arxiv_id}</span>}
                  </div>
                )}
              </>
            ) : (
              <a className="ref-raw" href={refLink(r)} target="_blank" rel="noreferrer">
                {r.raw}
              </a>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
