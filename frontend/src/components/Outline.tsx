import { useStore } from "../store";

// Left rail: section outline for quick navigation.
export function Outline() {
  const pages = useStore((s) => s.pages);
  const setGoto = useStore((s) => s.setGoto);
  const sections = pages?.sections || [];
  if (sections.length === 0) return null;
  return (
    <div className="outline">
      <div className="outline-head">Outline</div>
      <div className="outline-list">
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
