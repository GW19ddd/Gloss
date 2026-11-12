import { create } from "zustand";
import {
  api,
  ChatAttachment,
  Drawing,
  Highlight,
  ImportJob,
  PagesResponse,
  Paper,
  PdfAnnotation,
  PluginSnapshot,
  ProviderConnectionStatus,
  ProviderTestResult,
} from "./api/client";
import { mergeImportJobSnapshots } from "./importQueue.mjs";

let importMutation = 0;
let importRefreshInFlight: Promise<void> | null = null;
let papersRequestSequence = 0;
let papersAppliedSequence = 0;

export interface Selection {
  text: string;
  page: number;
  rects: [number, number, number, number][]; // in PDF points
}

interface State {
  papers: Paper[];
  importJobs: ImportJob[];
  view: "library" | "reader";
  current: Paper | null;
  pages: PagesResponse | null;
  highlights: Highlight[];
  drawings: Drawing[];
  /** markup read out of the PDF file itself (evidence + third-party marks) */
  pdfAnnotations: PdfAnnotation[];
  chatAttachments: ChatAttachment[];
  pluginSnapshot: PluginSnapshot;
  selection: Selection | null;
  activeTab: string;
  targetLanguage: string;
  outputLanguage: string;
  uiLang: "en" | "zh"; // interface-chrome language (NOT content/translation language)
  scholarView: { key: string | null; query: string }; // persists across tab switches
  providers: string[];
  provider: string;
  providerStatuses: Record<string, ProviderConnectionStatus>;
  gotoPage: number | null;
  /** PDF-space y of the passage a jump is aiming at, so it lands on screen. */
  gotoAnchor: number | null;
  flash: { page: number; rects: [number, number, number, number][]; id: number } | null;
  toast: string | null;
  selectionAction: { kind: string; selection: Selection; id: number } | null;
  settingsFocus: string | null;
  /** Bumped when the reader asks to go back to where a jump started from. */
  jumpBackTick: number;
  /** Quote to look for inside the note, set from a highlight (both directions). */
  noteQuery: string;
  /** Page the reader is on, kept so a regeneration can scope to "this section". */
  currentPage: number;
  /** A passage handed to the personal note from a PDF selection. */
  notePrompt: { text: string; page: number; id: number } | null;

  loadPapers: () => Promise<void>;
  loadImportJobs: () => Promise<void>;
  enqueueImport: (query: string) => Promise<ImportJob>;
  cancelImport: (id: string) => Promise<void>;
  openPaper: (id: string) => Promise<void>;
  closePaper: () => void;
  setTab: (t: string) => void;
  openFeatureSettings: (featureId: string | null) => void;
  setUiLang: (l: "en" | "zh") => void;
  setScholarView: (v: { key: string | null; query: string }) => void;
  flashLocate: (page: number, rects: [number, number, number, number][]) => void;
  clearFlash: () => void;
  setSelection: (s: Selection | null) => void;
  refreshHighlights: () => Promise<void>;
  refreshPages: () => Promise<void>;
  refreshDrawings: () => Promise<void>;
  refreshPdfAnnotations: () => Promise<void>;
  deletePdfAnnotation: (xref: number, source: string) => Promise<void>;
  loadPlugins: () => Promise<void>;
  loadSettings: () => Promise<void>;
  refreshProviderStatuses: () => Promise<void>;
  checkProvider: (provider: string) => Promise<ProviderTestResult>;
  switchProvider: (provider: string) => Promise<void>;
  setGoto: (p: number | null, anchor?: number | null) => void;
  notify: (m: string | null) => void;
  requestJumpBack: () => void;
  setNoteQuery: (q: string) => void;
  setCurrentPage: (page: number) => void;
  noteSelection: () => void;
  runSelectionAction: (kind: "explain" | "translate" | "ask") => void;
  askAboutText: (text: string) => void;
  addChatAttachment: (attachment: ChatAttachment) => void;
  removeChatAttachment: (id: string) => void;
  clearChatAttachments: () => void;
  addUserHighlight: (color?: string, note?: string) => Promise<void>;
  syncHighlightsToPdf: () => Promise<number>;
}

// papers whose outline auto-fix already ran this session (no retry loops)
const outlineAutoTried = new Set<string>();

export const useStore = create<State>((set, get) => ({
  papers: [],
  importJobs: [],
  view: "library",
  current: null,
  pages: null,
  highlights: [],
  drawings: [],
  pdfAnnotations: [],
  chatAttachments: [],
  pluginSnapshot: {
    api_version: 1,
    permissions: [],
    contribution_points: [],
    core: [],
    marketplace: [],
    installed: [],
    coming_soon: [],
  },
  selection: null,
  activeTab: "summary",
  targetLanguage: "中文 (Simplified Chinese)",
  outputLanguage: "中文 (Simplified Chinese)",
  uiLang: (localStorage.getItem("gloss.uiLang") as "en" | "zh") || "en",
  providers: [],
  provider: "local_claude",
  providerStatuses: {},
  gotoPage: null,
  gotoAnchor: null,
  flash: null,
  toast: null,
  selectionAction: null,
  settingsFocus: null,
  jumpBackTick: 0,
  noteQuery: "",
  currentPage: 0,
  notePrompt: null,
  scholarView: { key: null, query: "" },

  loadPapers: async () => {
    const requestSequence = ++papersRequestSequence;
    const { papers } = await api.listPapers();
    // Apply the newest successful response. A slower, older request can no
    // longer overwrite a library refresh triggered by a completed import.
    if (requestSequence > papersAppliedSequence) {
      papersAppliedSequence = requestSequence;
      set({ papers });
    }
  },
  loadImportJobs: () => {
    if (importRefreshInFlight) return importRefreshInFlight;
    const mutationAtStart = importMutation;
    importRefreshInFlight = (async () => {
      const { jobs } = await api.listImportJobs();
      if (mutationAtStart !== importMutation) return;

      const previous = get().importJobs;
      const merged = mergeImportJobSnapshots(previous, jobs) as ImportJob[];
      const previousById = new Map(previous.map((job) => [job.id, job]));
      const newlyCompleted = merged.filter(
        (job) => job.status === "completed" && previousById.get(job.id)?.status !== "completed",
      );
      const newlyFailed = merged.filter(
        (job) => job.status === "failed" && previousById.get(job.id)?.status !== "failed",
      );
      const completedNeedingRefresh = merged.filter(
        (job) =>
          job.status === "completed" &&
          job.paper_id &&
          !get().papers.some((paper) => paper.id === job.paper_id),
      );

      if (newlyCompleted.length || completedNeedingRefresh.length) {
        // Publish "completed" only after the library refresh succeeds. If the
        // backend is briefly unavailable, the next poll retries this refresh.
        await get().loadPapers();
      }
      set({ importJobs: merged });

      if (newlyCompleted.length) {
        const latest = newlyCompleted[newlyCompleted.length - 1];
        get().notify(`Imported: ${(latest.title || latest.query).slice(0, 50)}`);
      } else if (newlyFailed.length) {
        const latest = newlyFailed[newlyFailed.length - 1];
        get().notify(`Import failed: ${latest.error || latest.query}`);
      }
    })().finally(() => {
      importRefreshInFlight = null;
    });
    return importRefreshInFlight;
  },
  enqueueImport: async (query) => {
    const job = await api.enqueueImport(query);
    importMutation += 1;
    set((state) => ({
      importJobs: [...state.importJobs.filter((item) => item.id !== job.id), job],
    }));
    return job;
  },
  cancelImport: async (id) => {
    const previousJob = get().importJobs.find((job) => job.id === id);
    importMutation += 1;
    set((state) => ({
      importJobs: state.importJobs.map((job) =>
        job.id === id && !["completed", "failed", "cancelled"].includes(job.status)
          ? {
              ...job,
              status: "cancelling",
              stage_detail: "Cancelling import",
              revision: job.revision + 1,
            }
          : job,
      ),
    }));
    try {
      await api.cancelImportJob(id);
      importMutation += 1;
      set((state) => ({ importJobs: state.importJobs.filter((job) => job.id !== id) }));
      // If completion won the server-side race, DELETE clears only the job and
      // keeps the finished paper. Refreshing is harmless for a true cancel.
      await get().loadPapers();
    } catch (error) {
      importMutation += 1;
      if (previousJob) {
        set((state) => ({
          importJobs: state.importJobs.map((job) => job.id === id ? previousJob : job),
        }));
      }
      try {
        await get().loadPapers();
      } catch {
        // The next successful queue poll retries completed-paper refreshes.
      }
      throw error;
    }
  },
  refreshPages: async () => {
    const id = get().current?.id;
    if (!id) return;
    // The outline is cached per answer language, so the language goes along.
    set({ pages: await api.getPages(id, get().outputLanguage) });
  },
  openPaper: async (id) => {
    const [paper, pages] = await Promise.all([
      api.getPaper(id),
      api.getPages(id, get().outputLanguage),
    ]);
    set({
      current: paper, pages, view: "reader",
      // Reopening a paper comes back to the panel the reader was last on.
      activeTab: localStorage.getItem("gloss.tab") || "summary",
      selection: null, noteQuery: "",
      highlights: [], drawings: [], pdfAnnotations: [], chatAttachments: [],
      scholarView: { key: null, query: "" },
    });
    // A messy outline (formula fragments, duplicate headings) gets one silent
    // AI cleanup per paper per session, without blocking the reader.
    if (pages.outline_noisy && !outlineAutoTried.has(id)) {
      outlineAutoTried.add(id);
      void (async () => {
        try {
          await api.fixOutline(id, { language: get().outputLanguage });
          if (get().current?.id === id) {
            await get().refreshPages();
            get().notify(
              get().uiLang === "zh" ? "检测到大纲混乱，已自动修复" : "Messy outline detected and auto-fixed"
            );
          }
        } catch {
          /* auto-fix is best-effort; the manual button still works */
        }
      })();
    }
    await Promise.all([
      get().refreshHighlights(),
      get().refreshDrawings(),
      get().refreshPdfAnnotations(),
    ]);
  },
  closePaper: () => set({
    view: "library", current: null, pages: null, highlights: [], drawings: [],
    pdfAnnotations: [], chatAttachments: [], selection: null,
  }),
  setTab: (t) => {
    // Remembered so reopening a paper lands on the panel the reader left off on.
    localStorage.setItem("gloss.tab", t);
    set({ activeTab: t });
  },
  openFeatureSettings: (featureId) => set({ activeTab: "settings", settingsFocus: featureId }),
  setUiLang: (l) => {
    localStorage.setItem("gloss.uiLang", l);
    set({ uiLang: l });
  },
  setScholarView: (v) => set({ scholarView: v }),
  flashLocate: (page, rects) => set({
    flash: { page, rects, id: Date.now() },
    gotoPage: page,
    // Land on the passage itself, not merely on its page: a quote at the
    // bottom of a tall page is off-screen if we only scroll to the top.
    gotoAnchor: rects.length ? rects[0][1] : null,
  }),
  clearFlash: () => set({ flash: null }),
  setSelection: (s) => set({ selection: s }),
  refreshHighlights: async () => {
    const cur = get().current;
    if (!cur) return;
    const { highlights } = await api.listHighlights(cur.id);
    set({ highlights });
  },
  refreshDrawings: async () => {
    const cur = get().current;
    if (!cur) return;
    const { drawings } = await api.listDrawings(cur.id);
    set({ drawings });
  },
  refreshPdfAnnotations: async () => {
    const cur = get().current;
    if (!cur) return;
    try {
      const { annotations } = await api.listPdfAnnotations(cur.id);
      set({ pdfAnnotations: annotations || [] });
    } catch {
      set({ pdfAnnotations: [] });
    }
  },
  deletePdfAnnotation: async (xref, source) => {
    const cur = get().current;
    if (!cur) return;
    await api.deletePdfAnnotation(cur.id, xref, source);
    await get().refreshPdfAnnotations();
  },
  loadPlugins: async () => {
    try {
      const pluginSnapshot = await api.listPlugins();
      set({ pluginSnapshot });
    } catch {
      /* backend may still be starting */
    }
  },
  loadSettings: async () => {
    try {
      const s = await api.getSettings();
      const nextLanguage = s.config.output_language || s.config.target_language;
      const languageChanged = get().outputLanguage !== nextLanguage;
      set({
        providers: s.available_providers,
        provider: s.config.provider,
        providerStatuses: s.provider_statuses || {},
        targetLanguage: s.config.target_language,
        outputLanguage: nextLanguage,
      });
      // Changing the answer language changes the outline, so re-read it.
      if (languageChanged && get().current?.id) await get().refreshPages();
    } catch {
      /* backend not ready */
    }
  },
  refreshProviderStatuses: async () => {
    try {
      const result = await api.getProviderStatuses();
      set({ providerStatuses: result.provider_statuses || {} });
    } catch {
      /* backend not ready */
    }
  },
  checkProvider: async (provider) => {
    set((state) => ({
      providerStatuses: {
        ...state.providerStatuses,
        [provider]: {
          status: "checking",
          connected: false,
          error: "",
          checked_at: state.providerStatuses[provider]?.checked_at || null,
        },
      },
    }));
    try {
      const result = await api.testProvider(provider);
      set((state) => ({
        providerStatuses: {
          ...state.providerStatuses,
          [provider]: {
            status: result.ok ? "connected" : "error",
            connected: result.ok,
            error: result.error || "",
            checked_at: Date.now() / 1000,
          },
        },
      }));
      return result;
    } catch (error: any) {
      const message = String(error?.message || error);
      const result = { ok: false, provider, error: message };
      set((state) => ({
        providerStatuses: {
          ...state.providerStatuses,
          [provider]: {
            status: "error",
            connected: false,
            error: message,
            checked_at: Date.now() / 1000,
          },
        },
      }));
      return result;
    }
  },
  switchProvider: async (provider) => {
    const previous = get().provider;
    if (provider === previous) {
      await get().checkProvider(provider);
      return;
    }
    set({ provider });
    try {
      await api.updateSettings({ provider });
      get().notify(`AI provider: ${provider}`);
      await get().checkProvider(provider);
    } catch (error: any) {
      set({ provider: previous });
      get().notify(`Provider switch failed: ${String(error?.message || error)}`);
    }
  },
  setGoto: (p, anchor = null) => set({ gotoPage: p, gotoAnchor: anchor }),
  notify: (m) => set({ toast: m }),
  requestJumpBack: () => set((state) => ({ jumpBackTick: state.jumpBackTick + 1 })),
  setNoteQuery: (q) => set({ noteQuery: q }),
  setCurrentPage: (page) => {
    if (get().currentPage !== page) set({ currentPage: page });
  },
  runSelectionAction: (kind) => {
    const sel = get().selection;
    if (!sel) return;
    const tab = kind === "ask" ? "chat" : kind;
    localStorage.setItem("gloss.tab", tab);
    set({ activeTab: tab, selectionAction: { kind, selection: sel, id: Date.now() } });
  },
  noteSelection: () => {
    const sel = get().selection;
    if (!sel) return;
    // Hand the passage to the personal note so the reader never has to retype
    // what they just selected.
    localStorage.setItem("gloss.tab", "personal-notes");
    set({
      activeTab: "personal-notes",
      notePrompt: { text: sel.text, page: sel.page, id: Date.now() },
    });
  },
  askAboutText: (text) => {
    const t = (text || "").trim();
    if (!t) return;
    const sel = { text: t, page: 0, rects: [] as [number, number, number, number][] };
    // jump to chat and let ChatPanel's "ask" effect answer about the selection
    set({ selection: sel, activeTab: "chat", selectionAction: { kind: "ask", selection: sel, id: Date.now() } });
  },
  addChatAttachment: (attachment) => set((state) => ({
    chatAttachments: [...state.chatAttachments.filter((item) => item.id !== attachment.id), attachment].slice(-4),
    activeTab: "chat",
  })),
  removeChatAttachment: (id) => set((state) => ({
    chatAttachments: state.chatAttachments.filter((item) => item.id !== id),
  })),
  clearChatAttachments: () => set({ chatAttachments: [] }),
  addUserHighlight: async (color = "#ffd54f", note = "") => {
    const cur = get().current;
    const sel = get().selection;
    if (!cur || !sel) return;
    const saved = await api.addHighlight(cur.id, {
      page: sel.page,
      rects: sel.rects,
      text: sel.text,
      color,
      note,
      kind: "user",
    });
    await Promise.all([get().refreshHighlights(), get().refreshPdfAnnotations()]);
    get().notify(
      saved?.pdf_xref
        ? (get().uiLang === "zh" ? "标注已保存并写入 PDF" : "Highlight saved and written into the PDF")
        : "Highlight saved",
    );
  },
  syncHighlightsToPdf: async () => {
    const cur = get().current;
    if (!cur) return 0;
    const result = await api.syncHighlightsToPdf(cur.id);
    set({ highlights: result.highlights || [] });
    await get().refreshPdfAnnotations();
    get().notify(
      get().uiLang === "zh"
        ? `已把 ${result.written}/${result.total} 条标注写入 PDF`
        : `Wrote ${result.written}/${result.total} highlights into the PDF`,
    );
    return result.embedded || 0;
  },
}));
