import { useStore } from "../store";

const COLORS = ["#ffd54f", "#a5d6a7", "#90caf9", "#ef9a9a", "#ce93d8"];

export function SelectionPopover({
  pos,
  onClose,
}: {
  pos: { x: number; y: number };
  onClose: () => void;
}) {
  const run = useStore((s) => s.runSelectionAction);
  const addHl = useStore((s) => s.addUserHighlight);
  const selection = useStore((s) => s.selection);

  return (
    <div className="sel-popover" style={{ position: "fixed", left: pos.x, top: pos.y }} onMouseDown={(e) => e.preventDefault()}>
      <button onClick={() => { run("explain"); onClose(); }}>💡 Explain</button>
      <button onClick={() => { run("translate"); onClose(); }}>🌐 Translate</button>
      <button onClick={() => { run("ask"); onClose(); }}>💬 加入会话</button>
      <span className="hl-colors">
        {COLORS.map((c) => (
          <button
            key={c}
            className="hl-dot"
            style={{ background: c }}
            title="Highlight"
            onClick={() => { addHl(c); onClose(); }}
          />
        ))}
      </span>
      <button
        onClick={() => {
          if (selection) navigator.clipboard?.writeText(selection.text);
          onClose();
        }}
      >
        ⧉ Copy
      </button>
    </div>
  );
}
