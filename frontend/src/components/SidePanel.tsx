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

const TABS: [string, string][] = [
  ["summary", "Summary"],
  ["notes", "Notes"],
  ["mindmap", "Mind Map"],
  ["chat", "Chat"],
  ["explain", "Explain"],
  ["translate", "Translate"],
  ["highlights", "Highlights"],
  ["references", "References"],
  ["scholar", "Scholar"],
  ["skills", "Skills"],
  ["settings", "Settings"],
];

export function SidePanel() {
  const activeTab = useStore((s) => s.activeTab);
  const setTab = useStore((s) => s.setTab);
  const askAboutText = useStore((s) => s.askAboutText);
  const [ask, setAsk] = useState<{ x: number; y: number; text: string } | null>(null);

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
        {TABS.map(([id, label]) => (
          <button
            key={id}
            className={"tab" + (activeTab === id ? " active" : "")}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tab-content" onMouseUp={onMouseUp} onMouseDown={() => setAsk(null)}>
        {activeTab === "summary" && <SummaryPanel />}
        {activeTab === "notes" && <NotesPanel />}
        {activeTab === "mindmap" && <MindMapPanel />}
        {activeTab === "chat" && <ChatPanel />}
        {activeTab === "explain" && <ExplainPanel />}
        {activeTab === "translate" && <TranslatePanel />}
        {activeTab === "highlights" && <HighlightsPanel />}
        {activeTab === "references" && <ReferencesPanel />}
        {activeTab === "scholar" && <ScholarPanel />}
        {activeTab === "skills" && <SkillsPanel />}
        {activeTab === "settings" && <SettingsPanel />}
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
          💬 添加到会话
        </button>
      )}
    </div>
  );
}
