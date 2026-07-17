import { useStore } from "../store";

// Left rail: section outline for quick navigation. Resizable + collapsible (App owns width/collapse).
export function Outline({ onCollapse }: { onCollapse?: () => void }) {
  const pages = useStore((s) => s.pages);
  const setGoto = useStore((s) => s.setGoto);
  const sections = pages?.sections || [];
  return (
    <div className="outline">
      <div className="outline-head">
        <span>Outline</span>
        {onCollapse && (
          <button className="outline-collapse" title="Collapse outline" onClick={onCollapse}>
            «
          </button>
        )}
      </div>
      <div className="outline-list">
        {sections.length === 0 && (
          <div className="muted" style={{ padding: "8px 12px" }}>No sections detected</div>
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
