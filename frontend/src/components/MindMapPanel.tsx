import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { api, MindNode } from "../api/client";
import { useStore } from "../store";

// Initialize mermaid exactly once at module scope.
mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
  flowchart: { htmlLabels: true, curve: "basis" },
});

// Monotonic counter so each render() call gets a unique DOM id.
let mmCounter = 0;

const MAX_NODES = 60;

// Sanitize a raw node title into a mermaid-safe label.
function sanitizeLabel(raw: string): string {
  let s = (raw ?? "").toString();
  // collapse all whitespace (incl. newlines) to single spaces
  s = s.replace(/\s+/g, " ").trim();
  // drop characters that break mermaid string labels
  s = s.replace(/["`]/g, "");
  // brackets/braces/parens confuse the flowchart parser -> fullwidth / space
  s = s
    .replace(/\[/g, "【")
    .replace(/\]/g, "】")
    .replace(/\{/g, "｛")
    .replace(/\}/g, "｝")
    .replace(/\(/g, "（")
    .replace(/\)/g, "）");
  s = s.trim();
  if (s.length > 40) s = s.slice(0, 40).trim();
  if (!s) s = "·";
  return s;
}

// Deterministically convert a MindNode tree into a `graph LR` mermaid definition.
function treeToMermaid(tree: MindNode | null | undefined): string {
  const lines: string[] = ["graph LR"];
  if (!tree) {
    lines.push('n0["·"]');
    return lines.join("\n");
  }
  let counter = 0;
  const edges: string[] = [];

  function walk(node: MindNode): string | null {
    if (counter >= MAX_NODES) return null;
    const id = "n" + counter;
    counter++;
    lines.push(`${id}["${sanitizeLabel(node.title)}"]`);
    const children = node.children || [];
    for (const child of children) {
      if (counter >= MAX_NODES) break;
      const childId = walk(child);
      if (childId) edges.push(`${id} --> ${childId}`);
    }
    return id;
  }

  walk(tree);
  lines.push(...edges);
  return lines.join("\n");
}

// Recursive nested-list fallback rendered when mermaid fails.
function OutlineNode({ node, root }: { node: MindNode; root?: boolean }) {
  const label = sanitizeLabel(node.title);
  const children = node.children || [];
  return (
    <li>
      <span className={root ? "mm-root" : undefined}>{label}</span>
      {children.length > 0 && (
        <ul>
          {children.map((c, i) => (
            <OutlineNode key={i} node={c} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function MindMapPanel() {
  const current = useStore((s) => s.current);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [tree, setTree] = useState<MindNode | null>(null);
  const [fallbackTree, setFallbackTree] = useState<MindNode | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  async function load(refresh = false) {
    if (!current) return;
    setLoading(true);
    setErr("");
    setFallbackTree(null);
    try {
      const { tree } = await api.mindmap(current.id, refresh);
      setTree(tree);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setTree(null);
    setFallbackTree(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  // Render the mermaid diagram whenever the tree changes.
  useEffect(() => {
    let cancelled = false;
    if (!tree) {
      if (containerRef.current) containerRef.current.innerHTML = "";
      return;
    }
    setFallbackTree(null);
    const def = treeToMermaid(tree);
    (async () => {
      try {
        const { svg } = await mermaid.render("mm-" + mmCounter++, def);
        if (cancelled) return;
        if (containerRef.current) containerRef.current.innerHTML = svg;
      } catch {
        if (cancelled) return;
        if (containerRef.current) containerRef.current.innerHTML = "";
        setFallbackTree(tree);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tree]);

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button onClick={() => load(true)} disabled={loading || !current}>
          {loading ? "Mapping…" : "↻ Regenerate"}
        </button>
      </div>
      {err && <div className="error">{err}</div>}
      {loading && !tree && <div className="muted">Building the concept map…</div>}
      {fallbackTree && (
        <div className="muted">(diagram engine failed, showing outline)</div>
      )}
      {fallbackTree ? (
        <div className="mm-fallback">
          <ul>
            <OutlineNode node={fallbackTree} root />
          </ul>
        </div>
      ) : (
        <div className="mindmap-wrap" ref={containerRef} />
      )}
    </div>
  );
}
