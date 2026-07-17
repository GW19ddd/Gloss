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

// Hard cap on how many tree nodes we lay out (keeps huge maps readable + fast).
const MAX_NODES = 80;
// Layout geometry (deterministic left-to-right tidy tree).
const X_STEP = 260;
const Y_STEP = 64;

// Left-bar color by depth: root -> accent2, depth1 -> accent, then muted teal / gray.
const DEPTH_COLORS = ["var(--accent2)", "var(--accent)", "#4fb8a0", "#7f8aa0"];
function colorForDepth(depth: number): string {
  return DEPTH_COLORS[Math.min(depth, DEPTH_COLORS.length - 1)];
}

// ---------------------------------------------------------------------------
// Custom card node
// ---------------------------------------------------------------------------
interface MindNodeData {
  title: string;
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
  const bar = colorForDepth(d.depth);
  return (
    <div
      style={{
        position: "relative",
        minWidth: 150,
        maxWidth: 230,
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
        <span
          style={{
            display: "-webkit-box",
            WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            wordBreak: "break-word",
          }}
        >
          {d.title || "·"}
        </span>
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
    setLoading(true);
    setErr("");
    try {
      const { tree } = await api.mindmap(current.id, refresh);
      setTree(tree);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setTree(null);
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
              nodeColor={(n) => colorForDepth((n.data as MindNodeData)?.depth ?? 0)}
              style={{ background: "var(--bg2)" }}
            />
            <Controls />
          </ReactFlow>
        </div>
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
