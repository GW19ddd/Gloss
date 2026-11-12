// Typed API client for the Gloss backend, including POST-based SSE streaming.

import { fetchWithTimeout } from "./fetchWithTimeout.mjs";

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
export interface Chat {
  id: string;
  paper_id: string;
  title: string;
  created_at: number;
}

export type ImportJobStatus =
  | "queued"
  | "downloading"
  | "parsing"
  | "saving"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";

export interface ImportJob {
  id: string;
  query: string;
  status: ImportJobStatus;
  progress: number;
  stage_detail: string;
  title: string;
  paper_id: string | null;
  error: string | null;
  created_at: number;
  updated_at: number;
  revision: number;
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
  /** The number printed on each page, where the PDF declares one. */
  page_labels?: (string | null)[];
  /** true when the outline was AI-cleaned (POST fix_outline) */
  outline_fixed?: boolean;
  /** true when the raw outline looks broken (math fragments, duplicates) */
  outline_noisy?: boolean;
  /** "zh" | "en" — the language the returned outline is written in */
  outline_language?: string;
  /** true when the PDF's own bookmarks hold a Gloss outline */
  outline_written?: boolean;
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
  /** how the annotation is drawn in the PDF: 'highlight' | 'underline' | 'strikeout' */
  style?: string | null;
  /** xref of the native PDF annotation this highlight was written to (null = not embedded) */
  pdf_xref?: number | null;
}
/** Where annotations are currently written: the original PDF, or Gloss's own copy. */
export interface PdfTarget {
  path: string;
  is_original: boolean;
  exists: boolean;
  linked_path: string | null;
  linked_missing: boolean;
}
export interface PdfCandidate {
  path: string;
  name: string;
  score: number;
}
/**
 * A markup annotation read back out of the PDF file itself — note evidence and
 * marks left by Zotero or another reader, none of which are in Gloss's database.
 */
export interface PdfAnnotation {
  /** native object number; identifies it for deletion */
  xref: number;
  page: number;
  rects: [number, number, number, number][];
  color: string | null;
  content: string;
  title: string;
  author: string;
  type: string;
  /** which file it was read from */
  source: "copy" | "original";
  /** 'gloss' (mirrors a database highlight) | 'gloss_evidence' | 'external' */
  kind: string;
}
export interface PdfTargetLink {
  target: PdfTarget;
  sync: { written: number; removed: number; total: number; embedded: number };
}

export type DrawingTool = "pencil" | "pen" | "highlighter";
export interface Drawing {
  id: string;
  paper_id: string;
  page: number;
  points: [number, number][];
  color: string;
  width: number;
  tool: DrawingTool;
  note: string;
  created_at: number;
}
export interface PersonalNote {
  paper_id: string;
  content: string;
  updated_at: number | null;
}
/** A verbatim quote backing a claim in the AI deep note; `page`/`rects` locate it in the PDF. */
export interface NoteEvidence {
  id: string;
  quote: string;
  why: string;
  page: number | null;
  rects: [number, number, number, number][];
  /** False when only a shortened head of the quote matched: a hint, not a location. */
  exact?: boolean;
}
export interface DeepNote {
  markdown: string;
  evidence: NoteEvidence[];
}
/** An older version of the note, kept when a regeneration replaced it. */
export interface NoteVersion {
  at: string;
  scope: string;
  source: "ai" | "edited";
  markdown: string;
  evidence: NoteEvidence[];
}
/** Draft + the reader's own edit + the versions a regeneration archived. */
export interface NoteState {
  markdown: string;
  evidence: NoteEvidence[];
  edited: string | null;
  history: NoteVersion[];
  language: string;
}

/** Zotero's local API (Settings → Advanced must allow other applications). */
/** Whether Windows offers Gloss for PDF files, and the command it would run. */
export interface FileAssociationStatus {
  supported: boolean;
  registered: boolean;
  command: string | null;
}
/** A paper handed over by the OS (double-clicked PDF), returned only once. */
export interface PendingOpen {
  paper_id: string | null;
}
export interface ZoteroStatus {
  running: boolean;
  library_id: number | null;
  library_name: string | null;
  /** Zotero 10+ answers write requests; older ones are read-only (501). */
  writable: boolean;
  /** Whether Gloss already holds a local API key for those writes. */
  authorized: boolean;
  hint: string | null;
}
export interface ZoteroAttachment {
  key: string;
  title: string;
  path: string;
  linkMode: string | null;
  filename: string;
}
export interface ZoteroCandidate {
  key: string;
  title: string;
  year: string;
  authors: string[];
  doi: string;
  itemType: string | null;
  reason: string;
  attachments: ZoteroAttachment[];
}
export interface ZoteroLink {
  item_key: string | null;
  attachment_key: string | null;
  note_key: string | null;
}
export interface ZoteroAnnotationResult {
  evidence_id: string | null;
  key: string | null;
  reused: boolean;
  error?: string | null;
}
export interface ZoteroExportResult {
  /** Note HTML with every [E1] marker turned into a zotero:// link. */
  html: string;
  item_key: string;
  attachment_key: string;
  select_url: string;
  /** Key of the note Gloss created or overwrote, or null when Zotero refused it. */
  note_key: string | null;
  note_url: string | null;
  /** True when this export overwrote the note a previous export made. */
  note_updated?: boolean;
  /** True when the note is in Zotero already, so there is nothing to paste. */
  written: boolean;
  annotations: ZoteroAnnotationResult[];
  /** How many evidence items got a link that jumps straight to the passage. */
  matched: number;
  total: number;
  /** Zotero 10+ can take write requests, so Gloss could create annotations. */
  writable: boolean;
  authorized: boolean;
}
export interface ChatAttachment {
  id: string;
  kind: "pdf_region";
  page: number;
  image_data_url: string;
  extracted_text: string;
  bounds: [number, number, number, number];
}
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  attachments: ChatAttachment[];
}
export interface PluginManifest {
  api_version: 1;
  id: string;
  name: string;
  name_zh?: string;
  version: string;
  author: string;
  icon: string;
  description: string;
  description_zh?: string;
  tab_name: string;
  tab_name_zh?: string;
  contributes: {
    paper_sidebar?: {
      tab_name: string;
      tab_name_zh?: string;
      icon: string;
    };
    configuration?: {
      title?: string;
      properties?: Record<string, PluginConfigurationProperty>;
    };
  };
  agent?: PluginAgent;
  permissions: string[];
  requirements: string[];
  prompt: string;
  output: "markdown";
  builtin: boolean;
  installed?: boolean;
}
export interface PluginAgent {
  name?: string;
  name_zh?: string;
  icon?: string;
  messages?: Record<string, string | { en?: string; zh?: string }>;
}
export interface PluginConfigurationProperty {
  type?: "boolean" | "string" | "number" | "integer" | "array";
  title?: string;
  title_zh?: string;
  description?: string;
  description_zh?: string;
  markdownDescription?: string;
  default?: unknown;
  enum?: Array<string | number>;
  enumDescriptions?: string[];
  markdownEnumDescriptions?: string[];
  enumItemLabels?: string[];
  items?: { type?: string };
  minimum?: number;
  maximum?: number;
  order?: number;
}
export interface PluginRunResponse {
  status: "ready" | "unavailable";
  markdown: string;
  reason: { code: string; requirement: string } | null;
}
export interface CoreExtension {
  id: string;
  name: string;
  name_zh: string;
  icon: string;
  description: string;
  description_zh: string;
  builtin: true;
}
export interface PluginContributionPoint {
  id: string;
  status: "stable" | "planned";
  description: string;
}
export interface ComingSoonExtension {
  id: string;
  name: string;
  name_zh: string;
  icon: string;
  description: string;
  description_zh: string;
  planned_contribution: string;
}
export interface PluginSnapshot {
  api_version: number;
  permissions: string[];
  contribution_points: PluginContributionPoint[];
  core: CoreExtension[];
  marketplace: PluginManifest[];
  installed: PluginManifest[];
  coming_soon: ComingSoonExtension[];
}
export type AiTaskStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";
export interface AiTaskAgent {
  name?: string;
  name_zh?: string;
  icon?: string;
  messages?: Record<string, string | { en?: string; zh?: string }>;
}
export interface AiTaskSnapshot {
  id: string;
  feature_id: string;
  paper_id?: string | null;
  status: AiTaskStatus;
  progress: number;
  stage?: string;
  detail?: string;
  agent?: AiTaskAgent | string | null;
  result?: unknown;
  error?: string | null;
  created_at?: number | string;
  started_at?: number | string | null;
  updated_at?: number | string;
}
export interface CreateAiTaskRequest {
  feature_id: string;
  paper_id?: string;
  refresh?: boolean;
  language?: string;
  input?: Record<string, unknown> | string;
}
export interface AiArtifactRequest {
  feature_id: string;
  paper_id: string;
  language?: string;
}
export interface AiArtifactResponse {
  found: boolean;
  result?: unknown;
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
export type ProviderConnectionState = "unknown" | "checking" | "connected" | "error";
export interface ProviderConnectionStatus {
  status: ProviderConnectionState;
  connected: boolean;
  error: string;
  checked_at: number | null;
}
export interface ProviderTestResult {
  ok: boolean;
  provider: string;
  latency_ms?: number;
  reply?: string;
  error?: string;
}
export interface AiUsageAggregate {
  tasks: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  average_total_tokens: number;
  estimated_tasks: number;
}
export interface AiUsageRecord {
  id: string;
  task_type: string;
  provider: string;
  model: string | null;
  paper_id: string | null;
  plugin_id: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated: boolean;
  created_at: number;
}
export interface AiUsageSummary {
  total: AiUsageAggregate;
  by_task: (AiUsageAggregate & { task_type: string })[];
  recent: AiUsageRecord[];
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
export interface TexSection {
  title: string;
  count: number;
  done: number;
  units: { original: string; translation: string }[];
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

/** A sentence of a reflowed paragraph, with the PDF rectangles it occupies. */
export interface ReadingSegment {
  text: string;
  sent_id: string;
  rects: [number, number, number, number][];
}

export interface ReadingBlock {
  type: "p" | "heading" | "figure" | "caption";
  page: number;
  bbox: [number, number, number, number];
  image: string | null;
  text: string;
  segments: ReadingSegment[];
}

export interface ReadingDoc {
  blocks: ReadingBlock[];
  n_pages: number;
  /** PDF pages holding prose — a bilingual PDF's translated pages are skipped. */
  source_pages: number[];
  columns: 1 | 2;
  has_text: boolean;
  /** sentence id -> translated text; sentences with no entry are untranslated. */
  translations: Record<string, string>;
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
    fetchWithTimeout("/api/papers/import", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query }),
    }, 300_000, (r) => j<Paper>(r)),
  enqueueImport: (query: string) =>
    fetchWithTimeout(
      "/api/papers/import-jobs",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query }),
      },
      15_000,
      (r) => j<ImportJob>(r),
    ),
  listImportJobs: () =>
    fetchWithTimeout(
      "/api/papers/import-jobs",
      {},
      10_000,
      (r) => j<{ jobs: ImportJob[] }>(r),
    ),
  cancelImportJob: (id: string) =>
    fetch(`/api/papers/import-jobs/${id}`, { method: "DELETE" }).then((r) => j<{ ok: boolean }>(r)),
  pdfUrl: (id: string) => `/api/papers/${id}/pdf`,
  getReading: (id: string, language?: string) =>
    fetch(`/api/papers/${id}/reading${language ? `?lang=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<ReadingDoc>(r)),
  readingFigureUrl: (id: string, name: string) =>
    `/api/papers/${id}/reading/figure/${encodeURIComponent(name)}`,
  getPages: (id: string, language?: string) =>
    fetch(`/api/papers/${id}/pages${language ? `?language=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<PagesResponse>(r)),

  fixOutline: (id: string, opts: { refresh?: boolean; language?: string } = {}) =>
    fetch(`/api/papers/${id}/fix_outline`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(opts),
    }).then((r) => j<{ sections: Section[] }>(r)),

  resetOutline: (id: string, language?: string) =>
    fetch(
      `/api/papers/${id}/reset_outline${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { method: "POST" },
    ).then((r) => j<{ sections: Section[] }>(r)),

  // The outline follows the answer language, so the language is always sent.
  writeOutlineToPdf: (id: string, language?: string) =>
    fetch(`/api/papers/${id}/outline/to-pdf`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ language }),
    }).then((r) => j<{ written: number; language: string }>(r)),

  restorePdfOutline: (id: string) =>
    fetch(`/api/papers/${id}/outline/restore-pdf`, { method: "POST" })
      .then((r) => j<{ restored: number }>(r)),

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
  getTex: (paper_id: string) =>
    fetch(`/api/papers/${paper_id}/tex`).then((r) =>
      j<{ available: boolean; reason?: string; main: string | null; files: { name: string; tex: string }[] }>(r),
    ),
  locate: (paper_id: string, text: string) =>
    fetch(`/api/papers/${paper_id}/locate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => j<{ page: number | null; rects: [number, number, number, number][] }>(r)),
  getTranslations: (paper_id: string, language?: string) =>
    fetch(`/api/papers/${paper_id}/translations${language ? `?lang=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<{ sentences: TransSentence[]; pages: number[] }>(r)),
  getTexSections: (paper_id: string, language?: string) =>
    fetch(`/api/papers/${paper_id}/tex_sections${language ? `?lang=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<{ sections: TexSection[] }>(r)),
  translateTex: (paper_id: string, section: number | null, language?: string) =>
    fetch(`/api/papers/${paper_id}/translate_tex`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ section, language }),
    }).then((r) => j<{ sections: TexSection[] }>(r)),

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

  /** Draft + edit + history. Never starts an AI call. */
  getNoteState: (id: string, language?: string) =>
    fetch(`/api/papers/${id}/notes/state${language ? `?language=${encodeURIComponent(language)}` : ""}`)
      .then((r) => j<NoteState>(r)),
  saveNoteEdit: (id: string, markdown: string, language?: string) =>
    fetch(`/api/papers/${id}/notes/edit`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ markdown, language }),
    }).then((r) => j<NoteState>(r)),
  revertNoteEdit: (id: string, language?: string) =>
    fetch(`/api/papers/${id}/notes/revert?${language ? `language=${encodeURIComponent(language)}` : ""}`, {
      method: "POST",
    }).then((r) => j<NoteState>(r)),
  restoreNoteVersion: (id: string, index: number, language?: string) =>
    fetch(`/api/papers/${id}/notes/restore`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ index, language }),
    }).then((r) => j<NoteState>(r)),

  evidenceToPdf: (
    id: string,
    evidence: NoteEvidence[],
    target: "auto" | "original" | "dual" | "mono" | "both" | "copy" = "auto",
    side: "original" | "translated" | "both" = "original",
  ) =>
    fetch(`/api/papers/${id}/evidence/pdf`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ evidence, target, side }),
    }).then((r) => j<{ written: number; skipped: number; embedded: number }>(r)),

  /** Which translations of this paper are available to write evidence into. */
  evidencePdfStatus: (id: string) =>
    fetch(`/api/papers/${id}/evidence/pdf`).then(
      (r) =>
        j<{
          embedded: number;
          dual: { available: boolean; path: string | null; sidecar: boolean };
          mono: { available: boolean; path: string | null };
        }>(r),
    ),

  zoteroStatus: () => fetch("/api/zotero/status").then((r) => j<ZoteroStatus>(r)),

  zoteroSearch: (q: string, limit = 10) =>
    fetch(`/api/zotero/search?q=${encodeURIComponent(q)}&limit=${limit}`).then(
      (r) => j<{ candidates: ZoteroCandidate[] }>(r),
    ),

  zoteroLink: (id: string) =>
    fetch(`/api/papers/${id}/zotero/link`).then(
      (r) => j<{ link: ZoteroLink; status: ZoteroStatus }>(r),
    ),

  zoteroMatch: (id: string) =>
    fetch(`/api/papers/${id}/zotero/match`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    }).then((r) => j<{ candidates: ZoteroCandidate[]; link: ZoteroLink }>(r)),

  zoteroBind: (id: string, itemKey: string, attachmentKey?: string) =>
    fetch(`/api/papers/${id}/zotero/link`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ item_key: itemKey, attachment_key: attachmentKey }),
    }).then((r) => j<{ link: ZoteroLink }>(r)),

  zoteroAuthorize: () =>
    fetch("/api/zotero/authorize", { method: "POST" }).then(
      (r) => j<{ authorized: boolean; remember: boolean; status: ZoteroStatus }>(r),
    ),

  zoteroExport: (
    id: string,
    body: {
      html: string;
      evidence: NoteEvidence[];
      item_key?: string;
      attachment_key?: string;
      /** Set to overwrite the note an earlier export made instead of adding one. */
      note_key?: string;
    },
  ) =>
    fetch(`/api/papers/${id}/zotero/export`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<ZoteroExportResult>(r)),

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
  listPdfAnnotations: (id: string) =>
    fetch(`/api/papers/${id}/pdf-annotations`).then(
      (r) => j<{ annotations: PdfAnnotation[] }>(r),
    ),
  deletePdfAnnotation: (id: string, xref: number, source: string) =>
    fetch(`/api/papers/${id}/pdf-annotations/${xref}?source=${source}`, {
      method: "DELETE",
    }).then((r) => j<{ removed: number }>(r)),
  getPdfTarget: (id: string) =>
    fetch(`/api/papers/${id}/pdf-target`).then((r) => j<PdfTarget>(r)),
  linkPdfTarget: (id: string, path: string) =>
    fetch(`/api/papers/${id}/pdf-target`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    }).then((r) => j<PdfTargetLink>(r)),
  unlinkPdfTarget: (id: string) =>
    fetch(`/api/papers/${id}/pdf-target`, { method: "DELETE" }).then((r) => j<PdfTarget>(r)),
  detectPdfTarget: (id: string) =>
    fetch(`/api/papers/${id}/pdf-target/detect`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }).then((r) => j<{ candidates: PdfCandidate[]; searched: string[] }>(r)),
  syncHighlightsToPdf: (id: string) =>
    fetch(`/api/papers/${id}/highlights/sync-pdf`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }).then((r) => j<{ written: number; removed: number; total: number; embedded: number; highlights: Highlight[] }>(r)),
  patchHighlight: (hid: string, fields: any) =>
    fetch(`/api/highlights/${hid}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(fields),
    }).then((r) => j<Highlight>(r)),
  listDrawings: (id: string) =>
    fetch(`/api/papers/${id}/drawings`).then((r) => j<{ drawings: Drawing[] }>(r)),
  addDrawing: (id: string, drawing: Pick<Drawing, "page" | "points" | "color" | "width" | "tool">) =>
    fetch(`/api/papers/${id}/drawings`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(drawing),
    }).then((r) => j<Drawing>(r)),
  deleteDrawing: (drawingId: string) =>
    fetch(`/api/drawings/${drawingId}`, { method: "DELETE" }).then((r) => j<any>(r)),
  getPersonalNote: (id: string) =>
    fetch(`/api/papers/${id}/personal-note`).then((r) => j<PersonalNote>(r)),
  savePersonalNote: (id: string, content: string) =>
    fetch(`/api/papers/${id}/personal-note`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content }),
    }).then((r) => j<PersonalNote>(r)),

  listPlugins: () => fetch("/api/plugins").then((r) => j<PluginSnapshot>(r)),
  getPluginManifestSchema: () => fetch("/api/plugins/schema").then((r) => j<Record<string, unknown>>(r)),
  getPluginManifestTemplate: () => fetch("/api/plugins/template").then((r) => j<Record<string, unknown>>(r)),
  installMarketplacePlugin: (pluginId: string) =>
    fetch(`/api/plugins/${encodeURIComponent(pluginId)}/install`, { method: "POST" })
      .then((r) => j<PluginManifest>(r)),
  installPluginManifest: (manifest: Record<string, unknown>) =>
    fetch("/api/plugins/install", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ manifest }),
    }).then((r) => j<PluginManifest>(r)),
  uninstallPlugin: (pluginId: string) =>
    fetch(`/api/plugins/${encodeURIComponent(pluginId)}`, { method: "DELETE" })
      .then((r) => j<any>(r)),
  runPlugin: (pluginId: string, paperId: string, refresh = false) =>
    fetch(`/api/plugins/${encodeURIComponent(pluginId)}/papers/${paperId}/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh }),
    }).then((r) => j<PluginRunResponse>(r)),
  createAiTask: (request: CreateAiTaskRequest) =>
    fetch("/api/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    }).then((r) => j<AiTaskSnapshot>(r)),
  getAiTask: (id: string) =>
    fetch(`/api/tasks/${encodeURIComponent(id)}`).then((r) => j<AiTaskSnapshot>(r)),
  cancelAiTask: (id: string) =>
    fetch(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) => j<AiTaskSnapshot>(r)),
  getAiArtifact: (request: AiArtifactRequest) => {
    const query = new URLSearchParams({
      feature_id: request.feature_id,
      paper_id: request.paper_id,
    });
    if (request.language) query.set("language", request.language);
    return fetch(`/api/tasks/artifact?${query}`).then((r) => j<AiArtifactResponse>(r));
  },
  aiTaskEventsUrl: (id: string) => `/api/tasks/${encodeURIComponent(id)}/events`,

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
    fetch(`/api/papers/${paperId}/chats`).then((r) => j<{ chats: Chat[] }>(r)),
  createChat: (paperId: string, title = "Chat") =>
    fetch(`/api/papers/${paperId}/chats`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => j<Chat>(r)),
  getChatMessages: (chatId: string) =>
    fetch(`/api/chats/${chatId}/messages`).then((r) =>
      j<{ messages: ChatMessage[] }>(r),
    ),
  updateChatTitle: (chatId: string, title: string) =>
    fetch(`/api/chats/${chatId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => j<Chat>(r)),
  deleteChat: (chatId: string) =>
    fetch(`/api/chats/${chatId}`, { method: "DELETE" }).then((r) => j<any>(r)),

  listSkills: () => fetch("/api/skills").then((r) => j<{ skills: Skill[]; count: number }>(r)),

  testProvider: (provider: string) =>
    fetch("/api/settings/test", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider }),
    }).then((r) => j<ProviderTestResult>(r)),

  getSettings: () =>
    fetch("/api/settings").then((r) => j<{
      config: any;
      available_providers: string[];
      provider_statuses: Record<string, ProviderConnectionStatus>;
    }>(r)),
  getProviderStatuses: () =>
    fetch("/api/settings/status").then((r) =>
      j<{ provider_statuses: Record<string, ProviderConnectionStatus> }>(r),
    ),
  getAiUsage: (opts: { paper_id?: string; task_type?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.paper_id) query.set("paper_id", opts.paper_id);
    if (opts.task_type) query.set("task_type", opts.task_type);
    if (opts.limit) query.set("limit", String(opts.limit));
    const suffix = query.size ? `?${query.toString()}` : "";
    return fetch(`/api/usage${suffix}`).then((r) => j<AiUsageSummary>(r));
  },
  updateSettings: (patch: any) =>
    fetch("/api/settings", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => j<any>(r)),

  getFileAssociation: () =>
    fetch("/api/file-association").then((r) => j<FileAssociationStatus>(r)),
  setFileAssociation: (register: boolean) =>
    fetch("/api/file-association", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ register }),
    }).then((r) => j<FileAssociationStatus>(r)),

  /** The paper the OS asked for; the backend clears it as soon as it is read. */
  consumePendingOpen: () => fetch("/api/pending-open").then((r) => j<PendingOpen>(r)),
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
