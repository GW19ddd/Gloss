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
  const uiLang = useStore((s) => s.uiLang);
  const T = {
    en: { explain: "💡 Explain", translate: "🌐 Translate", ask: "💬 Add to chat", highlight: "Highlight", copy: "⧉ Copy" },
    zh: { explain: "💡 解释", translate: "🌐 翻译", ask: "💬 加入会话", highlight: "高亮", copy: "⧉ 复制" },
  }[uiLang];

  return (
    <div className="sel-popover" style={{ position: "fixed", left: pos.x, top: pos.y }} onMouseDown={(e) => e.preventDefault()}>
      <button onClick={() => { run("explain"); onClose(); }}>{T.explain}</button>
      <button onClick={() => { run("translate"); onClose(); }}>{T.translate}</button>
      <button onClick={() => { run("ask"); onClose(); }}>{T.ask}</button>
      <span className="hl-colors">
        {COLORS.map((c) => (
          <button
            key={c}
            className="hl-dot"
            style={{ background: c }}
            title={T.highlight}
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
        {T.copy}
      </button>
    </div>
  );
}
