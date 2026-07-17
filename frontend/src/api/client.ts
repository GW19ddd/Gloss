// Typed API client for the Gloss backend, including POST-based SSE streaming.

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year: string;
  abstract: string;
  source: string;
  arxiv_id: string;
  doi: string;
  n_pages: number;
  tags: string[];
  added_at: number;
}

export interface Block {
  id: number;
  bbox: [number, number, number, number];
  text: string;
  size: number;
  bold: boolean;
}
export interface PageInfo {
  index: number;
  width: number;
  height: number;
  blocks: Block[];
  images: number[][];
}
export interface Section {
  title: string;
  page: number;
  block_id: number | null;
  level: number;
}
export interface PagesResponse {
  n_pages: number;
  pages: PageInfo[];
  sections: Section[];
  toc: any[];
}
export interface Highlight {
  id: string;
  paper_id: string;
  page: number;
  rects: [number, number, number, number][];
  color: string;
  category: string;
  text: string;
  note: string;
  kind: string;
}
export interface Reference {
  id: string;
  idx: number;
  raw: string;
  title: string;
  authors: string[];
  year: string;
  doi: string;
  arxiv_id: string;
  url: string;
  abstract: string;
  resolved: number;
}
export interface Skill {
  id: string;
  name: string;
  source: string;
  type: string;
  description: string;
  argument_hint: string;
  allowed_tools: string[];
}
export interface Summary {
  tldr: string;
  problem: string;
  method: string;
  results: string;
  contributions: string[];
  key_points: string[];
  limitations: string[];
}
export interface MindNode {
  title: string;
  kind?: string;
  summary?: string;
  children?: MindNode[];
}
export interface TransSentence {
  page: number;
  original: string;
  translation: string;
}
export interface ScholarResult {
  title: string;
  abstract: string;
  year: any;
  authors: string[];
  url: string;
  arxiv_id: string;
  doi: string;
  source: string;
  citations?: number;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body.slice(0, 300)}`);
  }
  return r.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<any>(r)),

  listPapers: () => fetch("/api/papers").then((r) => j<{ papers: Paper[] }>(r)),
  getPaper: (id: string) => fetch(`/api/papers/${id}`).then((r) => j<Paper>(r)),
  deletePaper: (id: string) =>
    fetch(`/api/papers/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  uploadPaper: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/papers/upload", { method: "POST", body: fd }).then((r) => j<Paper>(r));
  },
  importPaper: (query: string) =>
    fetch("/api/papers/import", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query }),
    }).then((r) => j<Paper>(r)),
  pdfUrl: (id: string) => `/api/papers/${id}/pdf`,
  getPages: (id: string) => fetch(`/api/papers/${id}/pages`).then((r) => j<PagesResponse>(r)),

  summarize: (id: string, opts: { refresh?: boolean; language?: string } = {}) =>
    fetch(`/api/papers/${id}/summarize`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(opts),
    }).then((r) => j<Summary>(r)),

  explain: (body: { paper_id?: string; selection: string; context?: string; language?: string }) =>
    fetch("/api/explain", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<{ explanation: string }>(r)),

  translateText: (text: string, language?: string) =>
    fetch("/api/translate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, language }),
    }).then((r) => j<{ translation: string }>(r)),
  translatePages: (paper_id: string, page_start: number, page_end: number, language?: string) =>
    fetch("/api/translate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ paper_id, page_start, page_end, language }),
    }).then((r) => j<{ sentences: TransSentence[] }>(r)),
  getTranslations: (paper_id: string, language?: string) =>
    fetch(`/api/papers/${paper_id}/translations${language ? `?lang=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<{ sentences: TransSentence[]; pages: number[] }>(r)),

  autohighlight: (id: string) =>
    fetch(`/api/papers/${id}/autohighlight`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }).then((r) => j<{ highlights: Highlight[] }>(r)),

  mindmap: (id: string, refresh = false) =>
    fetch(`/api/papers/${id}/mindmap`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh }),
    }).then((r) => j<{ tree: MindNode }>(r)),

  notes: (id: string, refresh = false) =>
    fetch(`/api/papers/${id}/notes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh }),
    }).then((r) => j<{ markdown: string }>(r)),

  listHighlights: (id: string) =>
    fetch(`/api/papers/${id}/highlights`).then((r) => j<{ highlights: Highlight[] }>(r)),
  addHighlight: (id: string, h: Partial<Highlight>) =>
    fetch(`/api/papers/${id}/highlights`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(h),
    }).then((r) => j<Highlight>(r)),
  deleteHighlight: (hid: string) =>
    fetch(`/api/highlights/${hid}`, { method: "DELETE" }).then((r) => j<any>(r)),
  patchHighlight: (hid: string, fields: any) =>
    fetch(`/api/highlights/${hid}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(fields),
    }).then((r) => j<Highlight>(r)),

  getReferences: (id: string) =>
    fetch(`/api/papers/${id}/references`).then((r) => j<{ references: Reference[] }>(r)),
  resolveReferences: (id: string) =>
    fetch(`/api/papers/${id}/references/resolve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enrich: true }),
    }).then((r) => j<{ references: Reference[] }>(r)),

  scholarSearch: (q: string, k = 10) =>
    fetch(`/api/scholar/search?q=${encodeURIComponent(q)}&k=${k}`).then((r) =>
      j<{ results: ScholarResult[] }>(r),
    ),
  scholarRecommend: (id: string, k = 10) =>
    fetch(`/api/scholar/recommend?paper_id=${id}&k=${k}`).then((r) =>
      j<{ results: ScholarResult[] }>(r),
    ),

  // per-paper chat history
  listChats: (paperId: string) =>
    fetch(`/api/papers/${paperId}/chats`).then((r) => j<{ chats: any[] }>(r)),
  createChat: (paperId: string, title = "Chat") =>
    fetch(`/api/papers/${paperId}/chats`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => j<{ id: string }>(r)),
  getChatMessages: (chatId: string) =>
    fetch(`/api/chats/${chatId}/messages`).then((r) =>
      j<{ messages: { role: string; content: string }[] }>(r),
    ),
  deleteChat: (chatId: string) =>
    fetch(`/api/chats/${chatId}`, { method: "DELETE" }).then((r) => j<any>(r)),

  listSkills: () => fetch("/api/skills").then((r) => j<{ skills: Skill[]; count: number }>(r)),

  getSettings: () =>
    fetch("/api/settings").then((r) => j<{ config: any; available_providers: string[] }>(r)),
  updateSettings: (patch: any) =>
    fetch("/api/settings", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => j<any>(r)),
};

// POST-based SSE: reads a text/event-stream, parses `data: {json}` frames.
export async function streamPost(
  url: string,
  body: any,
  handlers: { onDelta?: (s: string) => void; onError?: (s: string) => void; onDone?: () => void },
  signal?: AbortSignal,
) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    handlers.onError?.(`HTTP ${resp.status}`);
    handlers.onDone?.();
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      try {
        const d = JSON.parse(line.slice(5).trim());
        if (d.delta) handlers.onDelta?.(d.delta);
        if (d.error) handlers.onError?.(d.error);
        if (d.done) handlers.onDone?.();
      } catch {
        /* ignore partial */
      }
    }
  }
  handlers.onDone?.();
}
