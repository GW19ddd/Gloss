import { create } from "zustand";
import { api, Highlight, PagesResponse, Paper } from "./api/client";

export interface Selection {
  text: string;
  page: number;
  rects: [number, number, number, number][]; // in PDF points
}

interface State {
  papers: Paper[];
  view: "library" | "reader";
  current: Paper | null;
  pages: PagesResponse | null;
  highlights: Highlight[];
  selection: Selection | null;
  activeTab: string;
  targetLanguage: string;
  outputLanguage: string;
  providers: string[];
  provider: string;
  gotoPage: number | null;
  toast: string | null;
  selectionAction: { kind: string; selection: Selection; id: number } | null;

  loadPapers: () => Promise<void>;
  openPaper: (id: string) => Promise<void>;
  closePaper: () => void;
  setTab: (t: string) => void;
  setSelection: (s: Selection | null) => void;
  refreshHighlights: () => Promise<void>;
  loadSettings: () => Promise<void>;
  setGoto: (p: number | null) => void;
  notify: (m: string | null) => void;
  runSelectionAction: (kind: "explain" | "translate" | "ask") => void;
  askAboutText: (text: string) => void;
  addUserHighlight: (color?: string) => Promise<void>;
}

export const useStore = create<State>((set, get) => ({
  papers: [],
  view: "library",
  current: null,
  pages: null,
  highlights: [],
  selection: null,
  activeTab: "summary",
  targetLanguage: "中文 (Simplified Chinese)",
  outputLanguage: "中文 (Simplified Chinese)",
  providers: [],
  provider: "local_claude",
  gotoPage: null,
  toast: null,
  selectionAction: null,

  loadPapers: async () => {
    const { papers } = await api.listPapers();
    set({ papers });
  },
  openPaper: async (id) => {
    const [paper, pages] = await Promise.all([api.getPaper(id), api.getPages(id)]);
    set({ current: paper, pages, view: "reader", activeTab: "summary", selection: null });
    get().refreshHighlights();
  },
  closePaper: () => set({ view: "library", current: null, pages: null, highlights: [], selection: null }),
  setTab: (t) => set({ activeTab: t }),
  setSelection: (s) => set({ selection: s }),
  refreshHighlights: async () => {
    const cur = get().current;
    if (!cur) return;
    const { highlights } = await api.listHighlights(cur.id);
    set({ highlights });
  },
  loadSettings: async () => {
    try {
      const s = await api.getSettings();
      set({
        providers: s.available_providers,
        provider: s.config.provider,
        targetLanguage: s.config.target_language,
        outputLanguage: s.config.output_language || s.config.target_language,
      });
    } catch {
      /* backend not ready */
    }
  },
  setGoto: (p) => set({ gotoPage: p }),
  notify: (m) => set({ toast: m }),
  runSelectionAction: (kind) => {
    const sel = get().selection;
    if (!sel) return;
    const tab = kind === "ask" ? "chat" : kind;
    set({ activeTab: tab, selectionAction: { kind, selection: sel, id: Date.now() } });
  },
  askAboutText: (text) => {
    const t = (text || "").trim();
    if (!t) return;
    const sel = { text: t, page: 0, rects: [] as [number, number, number, number][] };
    // jump to chat and let ChatPanel's "ask" effect answer about the selection
    set({ selection: sel, activeTab: "chat", selectionAction: { kind: "ask", selection: sel, id: Date.now() } });
  },
  addUserHighlight: async (color = "#ffd54f") => {
    const cur = get().current;
    const sel = get().selection;
    if (!cur || !sel) return;
    await api.addHighlight(cur.id, {
      page: sel.page,
      rects: sel.rects,
      text: sel.text,
      color,
      kind: "user",
    });
    await get().refreshHighlights();
    get().notify("Highlight saved");
  },
}));
