import {
  useEffect,
  useMemo,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { api, type NoteEvidence, type NoteState, type NoteVersion } from "../api/client";
import { useAiTask } from "../api/aiTasks";
import { useStore } from "../store";
import { AgentTaskCard } from "./AgentTaskCard";
import { Markdown } from "./Markdown";

/** A `##` chapter of the note, so a long note can be folded and navigated. */
interface NoteSection {
  title: string;
  body: string;
  index: number;
}

function splitSections(markdown: string): { intro: string; sections: NoteSection[] } {
  const intro: string[] = [];
  const sections: NoteSection[] = [];
  let current: NoteSection | null = null;
  for (const line of markdown.split("\n")) {
    const heading = /^##\s+(.*)$/.exec(line);
    if (heading) {
      current = { title: heading[1].trim(), body: "", index: sections.length };
      sections.push(current);
      continue;
    }
    if (current) current.body += `${line}\n`;
    else intro.push(line);
  }
  return { intro: intro.join("\n").trim(), sections };
}

function isState(value: unknown): value is NoteState {
  return !!value && typeof value === "object" && "markdown" in (value as object);
}

const T_ZH = {
  draft: "AI 草稿", mine: "我的修改", viewDraft: "看 AI 草稿", viewMine: "看我的版本",
  edit: "✎ 编辑", save: "保存", saving: "保存中…", saved: "已保存",
  saveFail: "保存失败，请重试", revert: "↺ 放弃修改，回到 AI 草稿",
  reverted: "已回到 AI 草稿（AI 原文仍保留）", versions: "版本",
  restored: "已恢复所选版本", preview: "预览", restore: "恢复此版本",
  regenerate: "↻ 重新生成", run: "生成 AI 笔记", scope: "范围",
  scopeFull: "全文", scopeSection: "本节",
  keepHint: "重新生成会先把当前内容存入「版本」，不会直接覆盖。",
  copy: "⧉ 复制", copied: "已复制到剪贴板", copyFail: "复制失败，请改用下载",
  download: "⬇ 下载 .md", evidence: "原文证据（点击跳转）",
  jump: "跳转到原文对应位置", unlocated: "这句没能在 PDF 里定位到",
  missing: "这句没能在 PDF 里定位到", approx: "定位为近似（只匹配到片段开头）",
  toc: "目录", exportHint: "更多导出方式在「导出」标签。",
};
const T_EN: Record<keyof typeof T_ZH, string> = {
  draft: "AI draft", mine: "My edit", viewDraft: "Show the AI draft", viewMine: "Show my version",
  edit: "✎ Edit", save: "Save", saving: "Saving…", saved: "Saved",
  saveFail: "Could not save — try again", revert: "↺ Discard my edit, back to the AI draft",
  reverted: "Back to the AI draft (the generated text is kept)", versions: "Versions",
  restored: "Version restored", preview: "Preview", restore: "Restore this version",
  regenerate: "↻ Regenerate", run: "Generate the AI note", scope: "Scope",
  scopeFull: "Whole paper", scopeSection: "This section",
  keepHint: "Regenerating archives the current text under Versions first.",
  copy: "⧉ Copy", copied: "Copied to clipboard", copyFail: "Copy failed, use download instead",
  download: "⬇ Download .md", evidence: "Evidence (click to jump)",
  jump: "Jump to the original passage", unlocated: "Not located in the PDF",
  missing: "Could not locate this quote in the PDF", approx: "Approximate: only the start matched",
  toc: "Contents", exportHint: "More export options live in the Export tab.",
};

/**
 * The AI deep note. Kept deliberately apart from the reader's own writing: the
 * model's text is a draft, the reader's edit is the note, and a regeneration
 * archives what it replaced instead of overwriting it.
 */
export function NotesPanel() {
  const current = useStore((state) => state.current);
  const outputLanguage = useStore((state) => state.outputLanguage);
  const uiLang = useStore((state) => state.uiLang);
  const flashLocate = useStore((state) => state.flashLocate);
  const notify = useStore((state) => state.notify);
  const pages = useStore((state) => state.pages);
  const currentPage = useStore((state) => state.currentPage);
  const noteQuery = useStore((state) => state.noteQuery);
  const T = uiLang === "zh" ? T_ZH : T_EN;

  const key = current ? `notes:${current.id}:${outputLanguage}` : null;
  const { task, running, error, start, restore, cancel } = useAiTask(key);
  useEffect(() => {
    if (!current) return;
    void restore({
      feature_id: "core.notes",
      paper_id: current.id,
      language: outputLanguage,
    });
  }, [key]);

  const raw = task?.result;
  // Local edits and restores sit on top of the cached result until the next
  // generation replaces it.
  const [override, setOverride] = useState<NoteState | null>(null);
  useEffect(() => {
    setOverride(null);
  }, [raw, key]);

  const state: NoteState = override
    || (isState(raw)
      ? (raw as NoteState)
      : {
        markdown: typeof raw === "string" ? raw : "",
        evidence: [],
        edited: null,
        history: [],
        language: outputLanguage,
      });

  const evidence: NoteEvidence[] = state.evidence || [];
  const hasEdit = typeof state.edited === "string";
  const [view, setView] = useState<"auto" | "draft" | "edited">("auto");
  const shown = view === "draft"
    ? state.markdown
    : view === "edited"
      ? (state.edited || state.markdown)
      : (hasEdit ? state.edited! : state.markdown);

  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [openSections, setOpenSections] = useState<Record<number, boolean>>({});
  const [tocOpen, setTocOpen] = useState(true);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [preview, setPreview] = useState<{ index: number; version: NoteVersion } | null>(null);

  // Which section the reader is in, so "regenerate this section" means something.
  const hereSection = useMemo(() => {
    let best: { title: string } | null = null;
    for (const section of pages?.sections || []) {
      if (section.page <= currentPage) best = { title: section.title };
      else break;
    }
    return best;
  }, [pages?.sections, currentPage]);

  const [scope, setScope] = useState("full");

  const run = (refresh: boolean) => {
    if (!current) return;
    const section = scope === "section" ? hereSection?.title : undefined;
    void start({
      feature_id: "core.notes",
      paper_id: current.id,
      refresh,
      language: outputLanguage,
      input: section ? { scope: "section", section } : { scope: "full" },
    });
  };

  /** The number printed on the page, where the PDF declares one. */
  function pageLabel(page: number) {
    return pages?.page_labels?.[page] || String(page + 1);
  }

  /** Scroll to a quote and flash it; retry the location if it was never found. */
  async function jump(id: string) {
    const ev = evidence.find((item) => item.id === id);
    if (!ev || !current) return;
    if (ev.page != null && ev.rects?.length) {
      flashLocate(ev.page, ev.rects);
      return;
    }
    // The quote was never located (or the note predates location). Try again
    // before telling the reader it cannot be found.
    try {
      const found = await api.locate(current.id, ev.quote);
      if (found?.page != null && found.rects?.length) {
        flashLocate(found.page, found.rects);
        return;
      }
    } catch {
      /* fall through to the honest message */
    }
    notify(T.missing);
  }

  function onDocClick(event: ReactMouseEvent<HTMLDivElement>) {
    const el = (event.target as HTMLElement).closest("[data-ev]");
    if (!el) return;
    event.preventDefault();
    void jump(el.getAttribute("data-ev") || "");
  }

  async function saveEdit() {
    if (!current) return;
    setSaveState("saving");
    try {
      setOverride(await api.saveNoteEdit(current.id, draftText, outputLanguage));
      setEditing(false);
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 2200);
    } catch {
      setSaveState("error");
    }
  }

  async function revertToDraft() {
    if (!current) return;
    try {
      setOverride(await api.revertNoteEdit(current.id, outputLanguage));
      setView("draft");
      notify(T.reverted);
    } catch (e) {
      notify(String(e));
    }
  }

  async function restoreVersion(index: number) {
    if (!current) return;
    try {
      setOverride(await api.restoreNoteVersion(current.id, index, outputLanguage));
      setPreview(null);
      setVersionsOpen(false);
      notify(T.restored);
    } catch (e) {
      notify(String(e));
    }
  }

  const withMarkers = useMemo(
    () => (shown || "").replace(/\[(E\d+)\]/g, (_m, id: string) => {
      const ev = evidence.find((item) => item.id === id);
      const located = ev && ev.page != null && ev.rects?.length;
      const cls = located
        ? (ev?.exact === false ? "ev-ref approx" : "ev-ref")
        : "ev-ref unlocated";
      const hint = located
        ? `${T.jump}${ev?.exact === false ? ` · ${T.approx}` : ""}`
        : T.unlocated;
      return `<a class="${cls}" data-ev="${id}" title="${hint}">${id}</a>`;
    }),
    [shown, evidence, T],
  );

  const { intro, sections } = useMemo(() => splitSections(withMarkers), [withMarkers]);
  const isOpen = (index: number) => openSections[index] !== false;

  // A highlight looking for its passage must not land on a folded chapter.
  useEffect(() => {
    const query = noteQuery.trim();
    if (!query) return;
    const hit = sections.findIndex((section) => section.body.includes(query));
    if (hit >= 0) setOpenSections((prev) => ({ ...prev, [hit]: true }));
  }, [noteQuery, sections]);

  function download() {
    const trail = evidence.length
      ? "\n\n## Evidence\n\n" + evidence
        .map((e) => `- **[${e.id}]** (p${e.page != null ? pageLabel(e.page) : "—"}): ${e.quote}${e.why ? ` — ${e.why}` : ""}`)
        .join("\n")
      : "";
    const blob = new Blob([shown + trail], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${(current?.title || "deep-paper-note").slice(0, 60)}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel-body">
      <div className="note-kind">
        <span className={`note-kind-tag ${hasEdit ? "mine" : "ai"}`}>
          {hasEdit ? T.mine : T.draft}
        </span>
        {hasEdit && (
          <button className="link" onClick={() => setView(view === "draft" ? "edited" : "draft")}>
            {view === "draft" ? T.viewMine : T.viewDraft}
          </button>
        )}
        <div className="spacer" />
        {!editing && shown && (
          <button onClick={() => { setDraftText(shown); setEditing(true); setSaveState("idle"); }} disabled={running}>
            {T.edit}
          </button>
        )}
      </div>

      <div className="panel-actions">
        <select value={scope} onChange={(event) => setScope(event.target.value)} disabled={running} title={T.scope}>
          <option value="full">{T.scopeFull}</option>
          <option value="section" disabled={!hereSection}>
            {T.scopeSection}{hereSection ? `（${hereSection.title.slice(0, 18)}）` : ""}
          </option>
        </select>
        <button onClick={() => run(true)} disabled={running || !current}>
          {state.markdown ? T.regenerate : T.run}
        </button>
        <button
          onClick={() => navigator.clipboard?.writeText(shown).then(
            () => notify(T.copied), () => notify(T.copyFail),
          )}
          disabled={running || !shown}
        >
          {T.copy}
        </button>
        <button onClick={download} disabled={running || !shown}>{T.download}</button>
      </div>
      {state.markdown && <div className="hint">{T.keepHint} {T.exportHint}</div>}

      {editing ? (
        <div className="note-editor">
          <textarea autoFocus value={draftText} onChange={(event) => setDraftText(event.target.value)} />
          <div className="note-editor-row">
            <button className="primary" onClick={() => void saveEdit()} disabled={saveState === "saving"}>
              {saveState === "saving" ? T.saving : T.save}
            </button>
            <button onClick={() => setEditing(false)}>✕</button>
            {saveState === "saved" && <span className="save-ok">{T.saved}</span>}
            {saveState === "error" && <span className="save-fail">{T.saveFail}</span>}
          </div>
        </div>
      ) : (
        <>
          {sections.length > 1 && (
            <div className="note-toc">
              <button className="note-toc-head" onClick={() => setTocOpen((open) => !open)}>
                {tocOpen ? "▾" : "▸"} {T.toc}
              </button>
              {tocOpen && (
                <ol>
                  {sections.map((section) => (
                    <li key={section.index}>
                      <button
                        onClick={() => {
                          setOpenSections((prev) => ({ ...prev, [section.index]: true }));
                          document.getElementById(`note-sec-${section.index}`)
                            ?.scrollIntoView({ behavior: "smooth", block: "start" });
                        }}
                      >
                        {section.title}
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          {shown && (
            <div className="notes-doc" onClick={onDocClick}>
              {intro && <Markdown text={intro} />}
              {sections.map((section) => (
                <section key={section.index} className="note-section" id={`note-sec-${section.index}`}>
                  <button
                    className="note-sec-head"
                    onClick={() => setOpenSections((prev) => ({
                      ...prev,
                      [section.index]: prev[section.index] === false,
                    }))}
                  >
                    <span className="caret">{isOpen(section.index) ? "▾" : "▸"}</span>
                    {section.title}
                  </button>
                  {isOpen(section.index) && (
                    <div className={noteQuery && section.body.includes(noteQuery) ? "note-sec-body hit" : "note-sec-body"}>
                      <Markdown text={section.body} />
                    </div>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {hasEdit && !editing && (
        <div className="note-actions">
          <button className="link" onClick={() => void revertToDraft()}>{T.revert}</button>
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {task && (running || task.status === "failed" || task.status === "cancelled") && (
        <AgentTaskCard
          task={task}
          uiLang={uiLang}
          agent={{
            name: "Deep Note Scholar",
            name_zh: "深度笔记学者",
            icon: "📚",
            messages: {
              generating: { en: "Writing the deep paper note", zh: "正在撰写深度论文笔记" },
            },
          }}
          onCancel={running ? () => void cancel() : undefined}
        />
      )}

      {state.history.length > 0 && (
        <div className="note-versions">
          <button className="link" onClick={() => setVersionsOpen((open) => !open)}>
            {versionsOpen ? "▾" : "▸"} {T.versions} ({state.history.length})
          </button>
          {versionsOpen && (
            <div className="note-version-list">
              {state.history.map((version, index) => (
                <div key={`${version.at}-${index}`} className="note-version">
                  <span className="note-version-meta">
                    {version.at || "—"} · {version.source === "edited" ? T.mine : T.draft}
                    {version.scope.startsWith("section:") ? ` · ${T.scopeSection}` : ""}
                  </span>
                  <span className="note-version-actions">
                    <button onClick={() => setPreview(preview?.index === index ? null : { index, version })}>
                      {T.preview}
                    </button>
                    <button onClick={() => void restoreVersion(index)}>{T.restore}</button>
                  </span>
                  {preview?.index === index && (
                    <pre className="note-version-preview">{version.markdown.slice(0, 1500)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {evidence.length > 0 && (
        <div className="ev-list">
          <h5>{T.evidence}</h5>
          {evidence.map((ev) => {
            const ok = ev.page != null && ev.rects.length > 0;
            return (
              <div
                key={ev.id}
                className={"ev-item" + (ok ? "" : " disabled")}
                onClick={() => void jump(ev.id)}
                title={ok ? (ev.exact === false ? `${T.jump} · ${T.approx}` : T.jump) : T.unlocated}
              >
                <span className="ev-badge">{ev.id}</span>
                <span className="ev-quote">
                  {ev.quote}
                  {ev.why && <em className="ev-why"> — {ev.why}</em>}
                </span>
                <span
                  className="ev-page"
                  title={ok ? `PDF ${uiLang === "zh" ? "第" : "page"} ${ev.page! + 1}` : undefined}
                >
                  {ok ? `p${pageLabel(ev.page!)}${ev.exact === false ? " ≈" : ""}` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
