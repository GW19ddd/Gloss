import { useEffect, useMemo, useRef, useState } from "react";
import { api, type ReadingBlock, type ReadingDoc, type ReadingSegment } from "../api/client";
import { useStore } from "../store";
import { SelectionPopover } from "./SelectionPopover";

type Rect = [number, number, number, number];

/** Pages translated per call — the backend caps a range at this many. */
const TRANSLATE_BATCH = 15;

const T = {
  en: {
    title: "Reading mode",
    original: "Original",
    translated: "Translated",
    loading: "Reflowing the paper…",
    empty: "This PDF has no text layer, so it cannot be reflowed.",
    failed: (e: string) => `Could not build the reading view: ${e}`,
    translateAll: "Translate the whole paper",
    translating: (done: number, total: number) => `Translating… ${done}/${total} pages`,
    translatedCount: (n: number) => `${n} pages translated`,
    noTranslation: "Nothing is translated yet.",
    reflowed: (n: number) => `Reflowed from ${n} pages`,
    twoCol: "two-column",
    oneCol: "single-column",
    bigger: "A+",
    smaller: "A−",
    close: "Close",
  },
  zh: {
    title: "阅读模式",
    original: "原文",
    translated: "译文",
    loading: "正在重排论文…",
    empty: "这份 PDF 没有文字层（扫描件），无法重排。",
    failed: (e: string) => `无法生成阅读视图：${e}`,
    translateAll: "翻译整篇",
    translating: (done: number, total: number) => `翻译中… ${done}/${total} 页`,
    translatedCount: (n: number) => `已翻译 ${n} 页`,
    noTranslation: "还没有译文。",
    reflowed: (n: number) => `由 ${n} 页重排`,
    twoCol: "双栏",
    oneCol: "单栏",
    bigger: "A+",
    smaller: "A−",
    close: "关闭",
  },
};

/** Trim a sentence's line rects to the part that was actually selected.

    A sentence often shares its line with neighbours, so the rects cover more
    than the words chosen. Splitting the sentence's characters evenly over its
    lines and cutting the first and last rect by the fraction selected is near
    enough — Zotero's own highlights are unions of line rectangles too.
 */
function sliceRects(rects: Rect[], start: number, end: number, length: number): Rect[] {
  if (start <= 0 && end >= length) return rects;
  const per = length / rects.length;
  const first = Math.min(rects.length - 1, Math.floor(start / per));
  const last = Math.min(rects.length - 1, Math.floor(Math.max(end - 1, start) / per));
  const out: Rect[] = [];
  for (let i = first; i <= last; i++) {
    const [x0, y0, x1, y1] = rects[i];
    const from = i === first ? (start - first * per) / per : 0;
    const to = i === last ? (end - last * per) / per : 1;
    out.push([x0 + (x1 - x0) * from, y0, x0 + (x1 - x0) * to, y1]);
  }
  return out;
}

function centerInside(a: Rect, b: Rect) {
  const cx = (a[0] + a[2]) / 2;
  const cy = (a[1] + a[3]) / 2;
  return cx >= b[0] && cx <= b[2] && cy >= b[1] && cy <= b[3];
}

export function ReadingMode({ onClose }: { onClose: () => void }) {
  const current = useStore((s) => s.current);
  const uiLang = useStore((s) => s.uiLang);
  const setSelection = useStore((s) => s.setSelection);
  const highlights = useStore((s) => s.highlights);
  const notify = useStore((s) => s.notify);
  const selectionAction = useStore((s) => s.selectionAction);
  const t = T[uiLang];

  const [doc, setDoc] = useState<ReadingDoc | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"original" | "translated">("original");
  const [scale, setScale] = useState(1);
  const [popover, setPopover] = useState<{ x: number; y: number } | null>(null);
  const [progress, setProgress] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  const paperId = current?.id;

  useEffect(() => {
    if (!paperId) return;
    let alive = true;
    setDoc(null);
    setError("");
    api
      .getReading(paperId)
      .then((d) => alive && setDoc(d))
      .catch((e: unknown) => alive && setError(String(e instanceof Error ? e.message : e)));
    return () => {
      alive = false;
    };
  }, [paperId]);

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPopover(null);
      onClose();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [onClose]);

  // Explain / translate / add-to-chat / write-in-note all switch to the panel
  // that answers, which sits behind this window — so step out of the way. A
  // highlight does not switch panels, and so must not close it.
  useEffect(() => {
    if (selectionAction) onClose();
  }, [selectionAction, onClose]);

  /** Which sentences already carry a highlight in the PDF. */
  const highlighted = useMemo(() => {
    const boxes = (highlights || []).flatMap((h) =>
      (h.rects || []).map((r) => ({ page: h.page, rect: r as Rect })),
    );
    return (page: number, seg: ReadingSegment) =>
      seg.rects.some((r) => boxes.some((b) => b.page === page && centerInside(r as Rect, b.rect)));
  }, [highlights]);

  const translatedPages = useMemo(() => {
    if (!doc) return 0;
    const ids = new Set(Object.keys(doc.translations || {}));
    if (!ids.size) return 0;
    const pages = new Set<number>();
    for (const b of doc.blocks) {
      for (const s of b.segments) if (ids.has(s.sent_id)) pages.add(b.page);
    }
    return pages.size;
  }, [doc]);

  async function translateAll() {
    if (!paperId || !doc || progress) return;
    const pages = doc.source_pages?.length
      ? doc.source_pages
      : Array.from({ length: doc.n_pages }, (_, i) => i);
    const total = pages.length;
    // Translate in runs of neighbouring pages: a bilingual PDF skips its
    // translated pages, so the prose pages are not one unbroken range.
    const runs: [number, number][] = [];
    let from = pages[0];
    let prev = pages[0];
    for (const p of pages.slice(1)) {
      if (p !== prev + 1) {
        runs.push([from, prev]);
        from = p;
      }
      prev = p;
    }
    runs.push([from, prev]);
    try {
      let done = 0;
      for (const [first, last] of runs) {
        for (let start = first; start <= last; start += TRANSLATE_BATCH) {
          setProgress(t.translating(done, total));
          await api.translatePages(paperId, start, Math.min(last, start + TRANSLATE_BATCH - 1));
          done += Math.min(TRANSLATE_BATCH, last - start + 1);
        }
      }
      setDoc(await api.getReading(paperId));
      setMode("translated");
    } catch (e) {
      notify(String(e instanceof Error ? e.message : e));
    } finally {
      setProgress("");
    }
  }

  function handleMouseUp(event: React.MouseEvent) {
    const container = bodyRef.current;
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : "";
    if (!container || !sel || !text || sel.rangeCount === 0) {
      setPopover(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const rects: Rect[] = [];
    let page: number | null = null;

    for (const span of Array.from(container.querySelectorAll<HTMLElement>("[data-seg]"))) {
      if (!range.intersectsNode(span)) continue;
      if (page === null) page = Number(span.dataset.page || "0");
      const full = span.textContent || "";
      const start = range.startContainer === span.firstChild ? range.startOffset : 0;
      const end = range.endContainer === span.firstChild ? range.endOffset : full.length;
      let segRects: Rect[] = [];
      try {
        segRects = JSON.parse(span.dataset.rects || "[]");
      } catch {
        segRects = [];
      }
      if (segRects.length) {
        rects.push(...sliceRects(segRects, start, end, full.length));
        continue;
      }
      // The PDF could not locate this sentence, so fall back to the box of the
      // paragraph it belongs to: a highlight somewhere beats no highlight.
      try {
        const box = JSON.parse(span.dataset.bbox || "null");
        if (box) rects.push(box);
      } catch {
        /* no geometry to fall back to */
      }
    }

    setSelection({ text, page: page ?? 0, rects });
    setPopover({ x: event.clientX + 8, y: event.clientY + 8 });
  }

  function renderSegment(block: ReadingBlock, seg: ReadingSegment, key: string) {
    const translated = mode === "translated" ? doc?.translations?.[seg.sent_id] : undefined;
    const isHl = highlighted(block.page, seg);
    return (
      <span
        key={key}
        data-seg=""
        data-page={block.page}
        data-rects={JSON.stringify(seg.rects)}
        data-bbox={JSON.stringify(block.bbox)}
        className={`rd-seg${isHl ? " rd-hl" : ""}${translated ? " rd-tr" : ""}`}
      >
        {translated || seg.text}{" "}
      </span>
    );
  }

  return (
    <div className="reading-backdrop" role="presentation">
      <div className="reading-window" role="dialog" aria-modal="true" aria-label={t.title}>
        <div className="reading-toolbar">
          <span className="reading-title">{t.title}</span>
          <div className="reading-modes">
            <button
              className={mode === "original" ? "active" : ""}
              onClick={() => setMode("original")}
            >
              {t.original}
            </button>
            <button
              className={mode === "translated" ? "active" : ""}
              onClick={() => setMode("translated")}
            >
              {t.translated}
            </button>
          </div>
          <div className="reading-zoom">
            <button onClick={() => setScale((s) => Math.max(0.8, s - 0.1))}>{t.smaller}</button>
            <button onClick={() => setScale((s) => Math.min(1.8, s + 0.1))}>{t.bigger}</button>
          </div>
          {doc && (
            <span className="reading-meta">
              {t.reflowed(doc.n_pages)} · {doc.columns === 2 ? t.twoCol : t.oneCol}
              {translatedPages ? ` · ${t.translatedCount(translatedPages)}` : ""}
            </span>
          )}
          {mode === "translated" && doc && !progress && (
            <button className="reading-translate" onClick={() => void translateAll()}>
              {translatedPages ? t.translatedCount(translatedPages) : t.translateAll}
            </button>
          )}
          {progress && <span className="reading-meta">{progress}</span>}
          <button className="reading-close" onClick={onClose} title={t.close}>
            ✕
          </button>
        </div>

        <div
          className="reading-body"
          ref={bodyRef}
          onMouseUp={handleMouseUp}
          style={{ fontSize: `${16 * scale}px` }}
        >
          {error && <p className="reading-empty">{t.failed(error)}</p>}
          {!doc && !error && <p className="reading-empty">{t.loading}</p>}
          {doc && !doc.has_text && <p className="reading-empty">{t.empty}</p>}
          {doc?.blocks.map((block, i) => {
            if (block.type === "figure") {
              return (
                <figure key={i} className="rd-figure">
                  <img
                    src={api.readingFigureUrl(paperId || "", block.image || "")}
                    alt={block.text || ""}
                  />
                  {block.text && <figcaption>{block.text}</figcaption>}
                </figure>
              );
            }
            if (block.type === "heading") {
              return (
                <h3 key={i} className="rd-heading">
                  {block.segments.map((seg, j) => renderSegment(block, seg, `${i}-${j}`))}
                </h3>
              );
            }
            return (
              <p key={i} className="rd-para">
                {block.segments.map((seg, j) => renderSegment(block, seg, `${i}-${j}`))}
              </p>
            );
          })}
        </div>
      </div>
      {popover && <SelectionPopover pos={popover} onClose={() => setPopover(null)} />}
    </div>
  );
}
