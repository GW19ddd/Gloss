import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  MiniMap,
  Controls,
  Handle,
  Position,
  type NodeProps,
  type NodeTypes,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, MindNode } from "../api/client";
import { useStore } from "../store";

// module-scoped cache so re-opening the tab is instant (no re-fetch/regenerate)
const MM_CACHE = new Map<string, MindNode>();

// Hard cap on how many tree nodes we lay out (keeps huge maps readable + fast).
const MAX_NODES = 80;
// Layout geometry (deterministic left-to-right tidy tree).
const X_STEP = 260;
const Y_STEP = 64;

// Left-bar color by depth (fallback when a node has no kind).
const DEPTH_COLORS = ["var(--accent2)", "var(--accent)", "#4fb8a0", "#7f8aa0"];
function colorForDepth(depth: number): string {
  return DEPTH_COLORS[Math.min(depth, DEPTH_COLORS.length - 1)];
}

// Primary coloring: by semantic KIND. Fallback to depth-based color when absent.
const KIND_COLOR: Record<string, string> = {
  root: "#a78bfa", problem: "#ef9a9a", method: "#90caf9", result: "#ffd54f",
  concept: "#ce93d8", contribution: "#a5d6a7", background: "#ffcc80",
  experiment: "#80deea", limitation: "#ef6b6b", data: "#b0bec5",
};
function colorForKind(kind: string | undefined, depth: number): string {
  if (kind && KIND_COLOR[kind]) return KIND_COLOR[kind];
  return colorForDepth(depth);
}

// ---------------------------------------------------------------------------
// Custom card node
// ---------------------------------------------------------------------------
interface MindNodeData {
  title: string;
  kind?: string;
  summary?: string;
  depth: number;
  isRoot: boolean;
  hasChildren: boolean;
  collapsed: boolean;
  focused: boolean;
  faded: boolean;
  [key: string]: unknown;
}

const hiddenHandle = {
  opacity: 0,
  width: 6,
  height: 6,
  minWidth: 6,
  minHeight: 6,
  border: "none",
  background: "transparent",
  pointerEvents: "none" as const,
};

function MindCardImpl({ data }: NodeProps) {
  const d = data as unknown as MindNodeData;
  const bar = colorForKind(d.kind, d.depth);
  return (
    <div
      style={{
        position: "relative",
        minWidth: 150,
        maxWidth: 250,
        background: "var(--bg2)",
        border: "1px solid var(--border)",
        borderLeft: `4px solid ${bar}`,
        borderRadius: 10,
        padding: "6px 10px",
        fontSize: 12.5,
        lineHeight: 1.3,
        color: "var(--fg)",
        fontWeight: d.isRoot ? 700 : 400,
        opacity: d.faded ? 0.25 : 1,
        boxShadow: d.focused
          ? "0 0 0 2px var(--accent), 0 0 16px rgba(122,162,247,.5)"
          : "none",
        transition: "opacity .18s ease, box-shadow .18s ease",
        cursor: "pointer",
      }}
    >
      <Handle type="target" position={Position.Left} style={hiddenHandle} />
      <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
        {d.hasChildren && (
          <span
            style={{
              flex: "0 0 auto",
              marginTop: 1,
              fontSize: 10,
              lineHeight: "16px",
              color: bar,
            }}
          >
            {d.collapsed ? "▸" : "▾"}
          </span>
        )}
        <div style={{ minWidth: 0 }}>
          {d.kind && (
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: bar,
                marginBottom: 1,
              }}
            >
              {d.kind}
            </div>
          )}
          <div
            style={{
              display: "-webkit-box",
              WebkitLineClamp: 3,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
              wordBreak: "break-word",
            }}
          >
            {d.title || "·"}
          </div>
          {d.summary && (
            <div
              style={{
                marginTop: 3,
                fontSize: 11,
                lineHeight: 1.35,
                color: "var(--fg-dim)",
                fontWeight: 400,
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
                wordBreak: "break-word",
              }}
            >
              {d.summary}
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} style={hiddenHandle} />
    </div>
  );
}
const MindCard = memo(MindCardImpl);

// Registered at module scope so React Flow never sees a new object each render.
const nodeTypes: NodeTypes = { mind: MindCard };

// ---------------------------------------------------------------------------
// Tree -> flat structure with stable ids (independent of collapse)
// ---------------------------------------------------------------------------
interface FlatNode {
  id: string;
  title: string;
  kind?: string;
  summary?: string;
  depth: number;
  parentId: string | null;
  childIds: string[];
}
interface Flat {
  byId: Map<string, FlatNode>;
  rootId: string | null;
  truncated: boolean;
}

function buildFlat(tree: MindNode | null): Flat {
  const byId = new Map<string, FlatNode>();
  let counter = 0;
  let truncated = false;

  function walk(node: MindNode, depth: number, parentId: string | null): string | null {
    if (counter >= MAX_NODES) {
      truncated = true;
      return null;
    }
    const id = "n" + counter;
    counter++;
    const flat: FlatNode = {
      id,
      title: (node.title ?? "").toString(),
      kind: node.kind ? node.kind.toString() : undefined,
      summary: node.summary ? node.summary.toString() : undefined,
      depth,
      parentId,
      childIds: [],
    };
    byId.set(id, flat);
    const children = node.children || [];
    for (const child of children) {
      if (counter >= MAX_NODES) {
        truncated = true;
        break;
      }
      const childId = walk(child, depth + 1, id);
      if (childId) flat.childIds.push(childId);
    }
    return id;
  }

  const rootId = tree ? walk(tree, 0, null) : null;
  return { byId, rootId, truncated };
}

// ---------------------------------------------------------------------------
// Flat + collapsed -> laid-out React Flow nodes/edges (post-order leaf packing)
// ---------------------------------------------------------------------------
function layout(flat: Flat, collapsed: Set<string>): { nodes: Node[]; edges: Edge[] } {
  const { byId, rootId } = flat;
  if (!rootId) return { nodes: [], edges: [] };

  const yById = new Map<string, number>();
  let leafCounter = 0;

  function place(id: string): number {
    const node = byId.get(id)!;
    const kids = collapsed.has(id) ? [] : node.childIds;
    let y: number;
    if (kids.length === 0) {
      y = leafCounter * Y_STEP;
      leafCounter++;
    } else {
      let sum = 0;
      for (const cid of kids) sum += place(cid);
      y = sum / kids.length;
    }
    yById.set(id, y);
    return y;
  }
  place(rootId);

  const nodes: Node[] = [];
  const edges: Edge[] = [];
  for (const [id, y] of yById) {
    const f = byId.get(id)!;
    nodes.push({
      id,
      type: "mind",
      position: { x: f.depth * X_STEP, y },
      data: {
        title: f.title,
        kind: f.kind,
        summary: f.summary,
        depth: f.depth,
        isRoot: f.parentId === null,
        hasChildren: f.childIds.length > 0,
        collapsed: collapsed.has(id),
        focused: false,
        faded: false,
      } as MindNodeData,
    });
    // Edge from parent -> this node (only when parent is also visible).
    if (f.parentId && yById.has(f.parentId)) {
      edges.push({
        id: `e-${f.parentId}-${id}`,
        source: f.parentId,
        target: id,
        type: "smoothstep",
      });
    }
  }
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
export function MindMapPanel() {
  const current = useStore((s) => s.current);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [tree, setTree] = useState<MindNode | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);

  async function load(refresh = false) {
    if (!current) return;
    if (!refresh && MM_CACHE.has(current.id)) {
      setTree(MM_CACHE.get(current.id)!);
      return;
    }
    setLoading(true);
    setErr("");
    try {
      const { tree } = await api.mindmap(current.id, refresh);
      MM_CACHE.set(current.id, tree);
      setTree(tree);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setTree(current && MM_CACHE.has(current.id) ? MM_CACHE.get(current.id)! : null);
    setCollapsed(new Set());
    setFocusedId(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  // Stable id assignment (only depends on the tree).
  const flat = useMemo(() => buildFlat(tree), [tree]);

  // Base layout: recomputes on tree + collapse changes only.
  const base = useMemo(() => layout(flat, collapsed), [flat, collapsed]);

  // Focus highlight set: focused node + its ancestors + its direct children.
  const highlight = useMemo(() => {
    const s = new Set<string>();
    if (!focusedId) return s;
    s.add(focusedId);
    let cur = flat.byId.get(focusedId);
    while (cur && cur.parentId) {
      s.add(cur.parentId);
      cur = flat.byId.get(cur.parentId);
    }
    const f = flat.byId.get(focusedId);
    if (f) for (const cid of f.childIds) s.add(cid);
    return s;
  }, [focusedId, flat]);

  // Inject focus/fade flags without triggering a relayout.
  const nodes = useMemo<Node[]>(() => {
    if (!focusedId) return base.nodes;
    return base.nodes.map((n) => ({
      ...n,
      data: {
        ...(n.data as MindNodeData),
        focused: n.id === focusedId,
        faded: !highlight.has(n.id),
      },
    }));
  }, [base.nodes, focusedId, highlight]);

  const edges = useMemo<Edge[]>(() => {
    return base.edges.map((e) => {
      const active = !!focusedId && (e.source === focusedId || e.target === focusedId);
      return {
        ...e,
        animated: active,
        style: {
          stroke: active ? "var(--accent)" : "var(--border)",
          strokeWidth: active ? 2 : 1.5,
        },
      };
    });
  }, [base.edges, focusedId]);

  const onNodeClick = useCallback(
    (_evt: React.MouseEvent, node: Node) => {
      setFocusedId(node.id);
      const info = flat.byId.get(node.id);
      if (info && info.childIds.length > 0) {
        setCollapsed((prev) => {
          const next = new Set(prev);
          if (next.has(node.id)) next.delete(node.id);
          else next.add(node.id);
          return next;
        });
      }
    },
    [flat],
  );

  const clearFocus = useCallback(() => setFocusedId(null), []);

  // Select a node from the details drawer: reuse the focus mechanism and make
  // sure the node is visible by expanding its (possibly collapsed) parent.
  const selectNode = useCallback(
    (id: string) => {
      setFocusedId(id);
      const info = flat.byId.get(id);
      if (info && info.parentId) {
        const parentId = info.parentId;
        setCollapsed((prev) => {
          if (!prev.has(parentId)) return prev;
          const next = new Set(prev);
          next.delete(parentId);
          return next;
        });
      }
    },
    [flat],
  );

  let body: React.ReactNode;
  if (!current) {
    body = (
      <div className="muted" style={{ flex: 1, padding: 16 }}>
        Open a paper to see its concept map.
      </div>
    );
  } else if (!tree) {
    body = (
      <div className="muted" style={{ flex: 1, padding: 16 }}>
        {loading ? "Building the concept map…" : "No concept map yet."}
      </div>
    );
  } else if (!flat.rootId) {
    body = (
      <div className="muted" style={{ flex: 1, padding: 16 }}>
        This paper has an empty concept map.
      </div>
    );
  } else {
    // Details-drawer data: selected node (== focused) + its connections.
    const selected = focusedId ? flat.byId.get(focusedId) ?? null : null;
    const parent =
      selected && selected.parentId ? flat.byId.get(selected.parentId) ?? null : null;
    const children = selected
      ? (selected.childIds
          .map((cid) => flat.byId.get(cid))
          .filter(Boolean) as FlatNode[])
      : [];
    const connRow = (n: FlatNode) => (
      <button
        key={n.id}
        onClick={() => selectNode(n.id)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          textAlign: "left",
          background: n.id === focusedId ? "var(--bg2)" : "none",
          border: "1px solid var(--border)",
          borderRadius: 7,
          padding: "5px 8px",
          marginBottom: 4,
          color: "var(--fg)",
          fontSize: 12,
          cursor: "pointer",
        }}
      >
        <span
          style={{
            flex: "0 0 auto",
            width: 8,
            height: 8,
            borderRadius: 2,
            background: colorForKind(n.kind, n.depth),
          }}
        />
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {n.title || "·"}
        </span>
      </button>
    );

    body = (
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        <div style={{ position: "absolute", inset: 0 }}>
          <ReactFlow
            key={current.id}
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            minZoom={0.1}
            maxZoom={2}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onNodeClick={onNodeClick}
            onPaneClick={clearFocus}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} size={1} color="#222a38" />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) =>
                colorForKind(
                  (n.data as MindNodeData)?.kind,
                  (n.data as MindNodeData)?.depth ?? 0,
                )
              }
              style={{ background: "var(--bg2)" }}
            />
            <Controls />
          </ReactFlow>
        </div>
        {selected && (
          <div
            style={{
              position: "absolute",
              top: 0,
              right: 0,
              bottom: 0,
              width: 260,
              background: "var(--panel)",
              borderLeft: "1px solid var(--border)",
              overflowY: "auto",
              padding: 12,
              zIndex: 5,
            }}
          >
            <button
              onClick={clearFocus}
              title="Close"
              style={{
                position: "absolute",
                top: 8,
                right: 8,
                background: "none",
                border: "none",
                color: "var(--fg-dim)",
                fontSize: 16,
                lineHeight: 1,
                cursor: "pointer",
              }}
            >
              ×
            </button>
            {selected.kind && (
              <span
                style={{
                  display: "inline-block",
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--bg2)",
                  background: colorForKind(selected.kind, selected.depth),
                  borderRadius: 5,
                  padding: "2px 6px",
                  marginBottom: 6,
                }}
              >
                {selected.kind}
              </span>
            )}
            <div
              style={{
                fontWeight: 700,
                fontSize: 14,
                lineHeight: 1.3,
                color: "var(--fg)",
                paddingRight: 16,
                wordBreak: "break-word",
              }}
            >
              {selected.title || "·"}
            </div>
            {selected.summary && (
              <div
                style={{
                  marginTop: 8,
                  fontSize: 12.5,
                  lineHeight: 1.45,
                  color: "var(--fg-dim)",
                  wordBreak: "break-word",
                }}
              >
                {selected.summary}
              </div>
            )}
            {(parent || children.length > 0) && (
              <div style={{ marginTop: 14 }}>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "var(--fg-dim)",
                    marginBottom: 6,
                  }}
                >
                  Connections
                </div>
                {parent && (
                  <>
                    <div style={{ fontSize: 10, color: "var(--fg-dim)", margin: "6px 0 3px" }}>
                      Parent
                    </div>
                    {connRow(parent)}
                  </>
                )}
                {children.length > 0 && (
                  <>
                    <div style={{ fontSize: 10, color: "var(--fg-dim)", margin: "8px 0 3px" }}>
                      Children ({children.length})
                    </div>
                    {children.map((c) => connRow(c))}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="panel-body"
      style={{ display: "flex", flexDirection: "column", padding: 0 }}
    >
      <div
        className="panel-actions"
        style={{ padding: "8px 12px", display: "flex", alignItems: "center", gap: 10 }}
      >
        <button onClick={() => load(true)} disabled={loading || !current}>
          {loading ? "Mapping…" : "↻ Regenerate"}
        </button>
        {loading && tree && <span className="muted">Updating…</span>}
        {flat.truncated && (
          <span className="muted" style={{ fontSize: 11 }}>
            Showing the first {MAX_NODES} nodes.
          </span>
        )}
        {focusedId && (
          <span className="muted" style={{ fontSize: 11 }}>
            Click empty space to clear focus.
          </span>
        )}
      </div>
      {err && <div className="error" style={{ padding: "0 12px 8px" }}>{err}</div>}
      {body}
    </div>
  );
}
