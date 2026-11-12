import { useEffect, useRef, useState } from "react";
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
import { PersonalNotesPanel } from "./PersonalNotesPanel";
import { TexPanel } from "./TexPanel";
import { ExtensionsPanel } from "./ExtensionsPanel";
import { ExportPanel } from "./ExportPanel";
import { PluginPanel } from "./PluginPanel";
import type { PluginManifest } from "../api/client";

interface TabDefinition {
  id: string;
  group: string;
  en: string;
  zh: string;
  icon?: string;
  C?: () => JSX.Element;
  plugin?: PluginManifest;
  arxivOnly?: boolean;
}

/** The five top-level entries. Everything else is one click deeper. */
const GROUPS: { id: string; en: string; zh: string; icon: string }[] = [
  { id: "guide", en: "Guide", zh: "导读", icon: "🧭" },
  { id: "qa", en: "Q&A", zh: "问答", icon: "💬" },
  { id: "notes", en: "Notes", zh: "笔记", icon: "📝" },
  { id: "research", en: "Research", zh: "研究分析", icon: "🔬" },
  { id: "export", en: "Export", zh: "导出", icon: "↗" },
];

const PANELS: TabDefinition[] = [
  { id: "summary", group: "guide", en: "Summary", zh: "速览", C: SummaryPanel },
  { id: "mindmap", group: "guide", en: "Mind Map", zh: "思维导图", C: MindMapPanel },
  { id: "tex", group: "guide", en: "TeX", zh: "TeX 源码", C: TexPanel, arxivOnly: true },
  { id: "chat", group: "qa", en: "Chat", zh: "对话", C: ChatPanel },
  { id: "explain", group: "qa", en: "Explain", zh: "解释", C: ExplainPanel },
  { id: "translate", group: "qa", en: "Translate", zh: "翻译", C: TranslatePanel },
  // The id must differ from the group id "notes": openTab() treats a group id
  // as "open whatever this group showed last", which would bounce the reader to
  // another panel instead of this one.
  { id: "personal-notes", group: "notes", en: "My Notes", zh: "我的笔记", C: PersonalNotesPanel },
  { id: "deep-note", group: "notes", en: "AI Note", zh: "AI 笔记", C: NotesPanel },
  { id: "highlights", group: "notes", en: "Marks", zh: "高亮批注", C: HighlightsPanel },
  { id: "references", group: "research", en: "References", zh: "参考文献", C: ReferencesPanel },
  { id: "scholar", group: "research", en: "Scholar", zh: "学术", C: ScholarPanel },
  { id: "export", group: "export", en: "Export", zh: "导出", C: ExportPanel },
];

/** Skills, extensions and model setup are configuration, not reading surfaces. */
const TOOLS: TabDefinition[] = [
  { id: "skills", group: "tools", en: "Skills", zh: "技能", C: SkillsPanel },
  { id: "extensions", group: "tools", en: "Extensions", zh: "插件", C: ExtensionsPanel },
  { id: "settings", group: "tools", en: "Settings", zh: "设置", C: SettingsPanel },
];

const DEFAULT_LEAF: Record<string, string> = {
  guide: "summary",
  qa: "chat",
  notes: "personal-notes",
  research: "references",
  export: "export",
  tools: "settings",
};

// Which panel each group last showed, so coming back to a group lands where
// the reader left it rather than at the top of the list.
const lastLeaf: Record<string, string> = { ...DEFAULT_LEAF };

export function SidePanel() {
  const activeTab = useStore((s) => s.activeTab);
  const setTab = useStore((s) => s.setTab);
  const askAboutText = useStore((s) => s.askAboutText);
  const uiLang = useStore((s) => s.uiLang);
  const current = useStore((s) => s.current);
  const installedPlugins = useStore((s) => s.pluginSnapshot.installed);
  const [ask, setAsk] = useState<{ x: number; y: number; text: string } | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!toolsOpen) return;
    const onDown = (event: MouseEvent) => {
      if (!toolsRef.current?.contains(event.target as Node)) setToolsOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [toolsOpen]);

  const pluginTabs: TabDefinition[] = installedPlugins.map((plugin) => {
    const panel = plugin.contributes?.paper_sidebar;
    const icon = panel?.icon || plugin.icon || "🧩";
    return {
      id: `plugin:${plugin.id}`,
      group: "research",
      en: panel?.tab_name || plugin.tab_name || plugin.name,
      zh: panel?.tab_name_zh || plugin.tab_name_zh || plugin.name_zh
        || panel?.tab_name || plugin.tab_name || plugin.name,
      icon,
      plugin,
    };
  });

  const tabs = [...PANELS, ...pluginTabs, ...TOOLS].filter(
    (t) => !t.arxivOnly || !!current?.arxiv_id,
  );
  const byId = new Map(tabs.map((tab) => [tab.id, tab]));

  const activeGroup = byId.get(activeTab)?.group
    || (GROUPS.some((g) => g.id === activeTab) ? activeTab : null)
    || "guide";

  // A restored tab this build no longer has (a plugin that was uninstalled)
  // must not leave the panel blank.
  useEffect(() => {
    if (activeTab === activeGroup || !byId.has(activeTab)) {
      const fallback = byId.has(lastLeaf[activeGroup] || "")
        ? lastLeaf[activeGroup]
        : (tabs.find((t) => t.group === activeGroup)?.id ?? "summary");
      setTab(fallback);
    }
  }, [activeTab, activeGroup]);

  useEffect(() => {
    const leaf = byId.get(activeTab);
    if (leaf) lastLeaf[leaf.group] = leaf.id;
  }, [activeTab]);

  const groupItems = tabs.filter((tab) => tab.group === activeGroup);

  function openTab(id: string) {
    const target = GROUPS.some((group) => group.id === id) ? lastLeaf[id] : id;
    setTab(target || id);
    setToolsOpen(false);
  }

  function onMouseUp(e: React.MouseEvent) {
    // don't offer "add to chat" from within the chat/settings tabs themselves
    if (activeTab === "chat" || activeTab === "settings") return setAsk(null);
    const text = window.getSelection()?.toString().trim() || "";
    if (text.length < 2) return setAsk(null);
    setAsk({ x: e.clientX, y: e.clientY, text });
  }

  const label = (tab: { en: string; zh: string }) => (uiLang === "zh" ? tab.zh : tab.en);

  return (
    <div className="side-panel">
      <div className="tabs-primary">
        {GROUPS.map((group) => (
          <button
            key={group.id}
            className={`tab-primary${activeGroup === group.id ? " active" : ""}`}
            onClick={() => openTab(group.id)}
            title={label(group)}
          >
            <span className="tab-icon" aria-hidden="true">{group.icon}</span>
            <span className="tab-text">{label(group)}</span>
          </button>
        ))}
        <div className="tools-menu" ref={toolsRef}>
          <button
            className={`tab-primary tools${activeGroup === "tools" ? " active" : ""}`}
            onClick={() => setToolsOpen((open) => !open)}
            title={uiLang === "zh" ? "技能、插件与设置" : "Skills, extensions, settings"}
            aria-haspopup="menu"
            aria-expanded={toolsOpen}
          >
            <span className="tab-icon" aria-hidden="true">⚙</span>
            <span className="tab-text">{uiLang === "zh" ? "工具" : "Tools"}</span>
          </button>
          {toolsOpen && (
            <div className="tools-pop" role="menu">
              {TOOLS.map((tool) => (
                <button
                  key={tool.id}
                  role="menuitem"
                  className={activeTab === tool.id ? "active" : ""}
                  onClick={() => openTab(tool.id)}
                >
                  {label(tool)}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {groupItems.length > 1 && (
        <div className="tabs-secondary">
          {activeGroup === "tools" && (
            <button className="tab-secondary back" onClick={() => openTab("guide")}>
              ←
            </button>
          )}
          {groupItems.map((tab) => (
            <button
              key={tab.id}
              className={`tab-secondary${activeTab === tab.id ? " active" : ""}`}
              onClick={() => openTab(tab.id)}
              title={label(tab)}
            >
              {tab.plugin && <span className="plugin-tab-icon" aria-hidden="true">{tab.icon}</span>}
              {label(tab)}
            </button>
          ))}
        </div>
      )}
      {/* Every panel stays mounted (hidden when inactive) so scroll position,
          mind-map pan/zoom, and in-flight work are preserved across tab switches. */}
      <div className="tab-content" onMouseUp={onMouseUp} onMouseDown={() => setAsk(null)}>
        {tabs.map((t) => {
          const C = t.C;
          return (
            <div key={t.id} className="tab-pane" style={{ display: activeTab === t.id ? "flex" : "none" }}>
              {t.plugin ? <PluginPanel plugin={t.plugin} /> : C ? <C /> : null}
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
