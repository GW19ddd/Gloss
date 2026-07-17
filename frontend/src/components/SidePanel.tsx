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
      <div className="tab-content">
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
    </div>
  );
}
