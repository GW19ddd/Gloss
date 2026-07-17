import { useState } from "react";
import { useStore } from "../store";
import { SummaryPanel } from "./SummaryPanel";
import { ExplainPanel } from "./ExplainPanel";
import { TranslatePanel } from "./TranslatePanel";
import { ChatPanel } from "./ChatPanel";
import { HighlightsPanel } from "./HighlightsPanel";
import { ReferencesPanel } from "./ReferencesPanel";
import { ScholarPanel } from "./ScholarPanel";
import { SkillsPanel } from "./SkillsPanel";
import { SettingsPanel } from "./SettingsPanel";
import { MindMapPanel } from "./MindMapPanel";
import { NotesPanel } from "./NotesPanel";
import { TexPanel } from "./TexPanel";

const TABS: { id: string; en: string; zh: string; C: () => JSX.Element; arxivOnly?: boolean }[] = [
  { id: "summary", en: "Summary", zh: "速览", C: SummaryPanel },
  { id: "notes", en: "Notes", zh: "笔记", C: NotesPanel },
  { id: "mindmap", en: "Mind Map", zh: "思维导图", C: MindMapPanel },
  { id: "chat", en: "Chat", zh: "对话", C: ChatPanel },
  { id: "explain", en: "Explain", zh: "解释", C: ExplainPanel },
  { id: "translate", en: "Translate", zh: "翻译", C: TranslatePanel },
  { id: "tex", en: "TeX", zh: "TeX 源码", C: TexPanel, arxivOnly: true },
  { id: "highlights", en: "Highlights", zh: "高亮", C: HighlightsPanel },
  { id: "references", en: "References", zh: "参考文献", C: ReferencesPanel },
  { id: "scholar", en: "Scholar", zh: "学术", C: ScholarPanel },
  { id: "skills", en: "Skills", zh: "技能", C: SkillsPanel },
  { id: "settings", en: "Settings", zh: "设置", C: SettingsPanel },
];

export function SidePanel() {
  const activeTab = useStore((s) => s.activeTab);
  const setTab = useStore((s) => s.setTab);
  const askAboutText = useStore((s) => s.askAboutText);
  const uiLang = useStore((s) => s.uiLang);
  const current = useStore((s) => s.current);
  const [ask, setAsk] = useState<{ x: number; y: number; text: string } | null>(null);
  // TeX tab only for arXiv papers (they have LaTeX source)
  const tabs = TABS.filter((t) => !t.arxivOnly || !!current?.arxiv_id);

  function onMouseUp(e: React.MouseEvent) {
    // don't offer "add to chat" from within the chat/settings tabs themselves
    if (activeTab === "chat" || activeTab === "settings") return setAsk(null);
    const text = window.getSelection()?.toString().trim() || "";
    if (text.length < 2) return setAsk(null);
    setAsk({ x: e.clientX, y: e.clientY, text });
  }

  return (
    <div className="side-panel">
      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={"tab" + (activeTab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {uiLang === "zh" ? t.zh : t.en}
          </button>
        ))}
      </div>
      {/* Every panel stays mounted (hidden when inactive) so scroll position,
          mind-map pan/zoom, and in-flight work are preserved across tab switches. */}
      <div className="tab-content" onMouseUp={onMouseUp} onMouseDown={() => setAsk(null)}>
        {tabs.map((t) => {
          const C = t.C;
          return (
            <div key={t.id} className="tab-pane" style={{ display: activeTab === t.id ? "flex" : "none" }}>
              <C />
            </div>
          );
        })}
      </div>
      {ask && (
        <button
          className="ask-chat-pop"
          style={{ position: "fixed", left: ask.x, top: ask.y + 10, zIndex: 40 }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            askAboutText(ask.text);
            window.getSelection()?.removeAllRanges();
            setAsk(null);
          }}
        >
          💬 {uiLang === "zh" ? "添加到会话" : "Add to chat"}
        </button>
      )}
    </div>
  );
}
