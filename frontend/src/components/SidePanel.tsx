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

const TABS: { id: string; en: string; zh: string }[] = [
  { id: "summary", en: "Summary", zh: "速览" },
  { id: "notes", en: "Notes", zh: "笔记" },
  { id: "mindmap", en: "Mind Map", zh: "思维导图" },
  { id: "chat", en: "Chat", zh: "对话" },
  { id: "explain", en: "Explain", zh: "解释" },
  { id: "translate", en: "Translate", zh: "翻译" },
  { id: "highlights", en: "Highlights", zh: "高亮" },
  { id: "references", en: "References", zh: "参考文献" },
  { id: "scholar", en: "Scholar", zh: "学术" },
  { id: "skills", en: "Skills", zh: "技能" },
  { id: "settings", en: "Settings", zh: "设置" },
];

export function SidePanel() {
  const activeTab = useStore((s) => s.activeTab);
  const setTab = useStore((s) => s.setTab);
  const askAboutText = useStore((s) => s.askAboutText);
  const uiLang = useStore((s) => s.uiLang);
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
        {TABS.map((t) => (
          <button
            key={t.id}
            className={"tab" + (activeTab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {uiLang === "zh" ? t.zh : t.en}
          </button>
        ))}
      </div>
      <div className="tab-content" onMouseUp={onMouseUp} onMouseDown={() => setAsk(null)}>
        {activeTab === "summary" && <SummaryPanel />}
        {activeTab === "notes" && <NotesPanel />}
        {activeTab === "mindmap" && <MindMapPanel />}
        {/* Chat stays mounted (hidden) so "Ask"/add-to-chat from the PDF or a panel
            lands reliably and per-paper history isn't lost when switching tabs. */}
        <div style={{ display: activeTab === "chat" ? "flex" : "none", flex: 1, minWidth: 0 }}>
          <ChatPanel />
        </div>
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
          💬 {uiLang === "zh" ? "添加到会话" : "Add to chat"}
        </button>
      )}
    </div>
  );
}
