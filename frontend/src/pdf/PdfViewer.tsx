import { useEffect, useRef, useState } from "react";
import { pdfjsLib, TextLayer } from "./pdfSetup";
import { api } from "../api/client";
import { useStore } from "../store";
import { SelectionPopover } from "../components/SelectionPopover";

// Use PDF.js's OFFICIAL text layer (v4 `TextLayer`) rather than a hand-rolled one,
// so selection matches a real browser PDF viewer — this uses the PDF's embedded
// text (not OCR); it's just rendered/positioned by pdf.js's own builder.
async function renderTextLayer(page: any, viewport: any, layer: HTMLDivElement) {
  layer.innerHTML = "";
  // v4 positions spans relative to this CSS variable
  layer.style.setProperty("--scale-factor", String(viewport.scale));
  if (TextLayer) {
    const tl = new TextLayer({
      textContentSource: page.streamTextContent({ includeMarkedContent: true }),
      container: layer,
      viewport,
    });
    await tl.render();
    return;
  }
  // fallback (older pdf.js): manual span positioning
  const tc = await page.getTextContent();
  const frag = document.createDocumentFragment();
  for (const item of tc.items as any[]) {
    if (!item.str) continue;
    const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
    const fontSize = Math.hypot(tx[2], tx[3]);
    const span = document.createElement("span");
    span.textContent = item.str;
    span.style.left = `${tx[4]}px`;
    span.style.top = `${tx[5] - fontSize}px`;
    span.style.fontSize = `${fontSize}px`;
    frag.appendChild(span);
  }
  layer.appendChild(frag);
}

export function PdfViewer() {
  const current = useStore((s) => s.current);
  const uiLang = useStore((s) => s.uiLang);
  const pages = useStore((s) => s.pages);
  const highlights = useStore((s) => s.highlights);
  const gotoPage = useStore((s) => s.gotoPage);
  const setGoto = useStore((s) => s.setGoto);
  const setSelection = useStore((s) => s.setSelection);
  const flash = useStore((s) => s.flash);
  const clearFlash = useStore((s) => s.clearFlash);

  const [scale, setScale] = useState(1.35);
  const [rendered, setRendered] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const docRef = useRef<any>(null);
  const [popover, setPopover] = useState<{ x: number; y: number } | null>(null);
  const [showHl, setShowHl] = useState(() => localStorage.getItem("gloss.showHl") !== "0");
  const [dispOpen, setDispOpen] = useState(false);
  const renderTasksRef = useRef<any[]>([]);

  // Load the PDF document once per paper.
  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    setRendered(false);
    const task = pdfjsLib.getDocument(api.pdfUrl(current.id));
    task.promise.then((doc: any) => {
      if (cancelled) return;
      docRef.current = doc;
      setRendered(true);
    });
    return () => {
      cancelled = true;
      try {
        docRef.current?.destroy();
      } catch {}
    };
  }, [current?.id]);

  // Render all pages whenever the doc is ready or the scale changes.
  useEffect(() => {
    const doc = docRef.current;
    if (!doc || !rendered) return;
    let cancelled = false;
    // cancel any in-flight renders from a previous scale so they don't collide
    // with the new ones on the same canvas (which makes PDF.js throw).
    renderTasksRef.current.forEach((t) => {
      try {
        t.cancel();
      } catch {}
    });
    renderTasksRef.current = [];
    // supersample: render the bitmap at >=2x the display size so text is crisp
    // even on 1x monitors, then let CSS downscale it to the layout size.
    const quality = Math.max(2, window.devicePixelRatio || 1);

    (async () => {
      const items: ({ page: any; vp: any } | null)[] = [];
      // pass 1 — size every page holder first so a zoom applies to ALL pages at once
      for (let i = 1; i <= doc.numPages; i++) {
        if (cancelled) return;
        const holder = pageRefs.current[i - 1];
        if (!holder) {
          items[i] = null;
          continue;
        }
        const page = await doc.getPage(i);
        const vp = page.getViewport({ scale });
        holder.style.width = `${vp.width}px`;
        holder.style.height = `${vp.height}px`;
        items[i] = { page, vp };
      }
      // pass 2 — render each page's bitmap + text layer (a failure on one page
      // must not abort the others)
      for (let i = 1; i <= doc.numPages; i++) {
        if (cancelled) return;
        const it = items[i];
        const holder = pageRefs.current[i - 1];
        if (!it || !holder) continue;
        const { page, vp } = it;
        const canvas = holder.querySelector("canvas") as HTMLCanvasElement;
        const textLayer = holder.querySelector(".textLayer") as HTMLDivElement;
        const rvp = page.getViewport({ scale: scale * quality });
        canvas.width = Math.floor(rvp.width);
        canvas.height = Math.floor(rvp.height);
        canvas.style.width = `${vp.width}px`;
        canvas.style.height = `${vp.height}px`;
        const ctx = canvas.getContext("2d")!;
        try {
          const task = page.render({ canvasContext: ctx, viewport: rvp });
          renderTasksRef.current.push(task);
          await task.promise;
          if (textLayer) await renderTextLayer(page, vp, textLayer);
        } catch {
          /* render cancelled (scale changed) or failed — leave this page for the next pass */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rendered, scale, current?.id]);

  // Scroll to a requested page/section.
  useEffect(() => {
    if (gotoPage == null) return;
    const el = pageRefs.current[gotoPage];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setGoto(null);
  }, [gotoPage]);

  // Auto-clear a transient flash highlight (from click-to-locate) after a moment.
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => clearFlash(), 1700);
    return () => clearTimeout(t);
  }, [flash?.id]);

  function onMouseUp() {
    const sel = window.getSelection();
    const text = sel?.toString().trim() || "";
    if (!text || !sel || sel.rangeCount === 0) {
      setPopover(null);
      return;
    }
    // find the page container of the selection
    let node: Node | null = sel.anchorNode;
    let pageEl: HTMLElement | null = null;
    while (node) {
      if (node instanceof HTMLElement && node.dataset.pageIndex != null) {
        pageEl = node;
        break;
      }
      node = node.parentNode;
    }
    if (!pageEl) {
      // maybe anchorNode is a text node inside .text-layer
      const anc = sel.anchorNode?.parentElement?.closest("[data-page-index]") as HTMLElement | null;
      pageEl = anc;
    }
    if (!pageEl) {
      setPopover(null);
      return;
    }
    const pageIndex = parseInt(pageEl.dataset.pageIndex!, 10);
    const pr = pageEl.getBoundingClientRect();
    const range = sel.getRangeAt(0);
    const clientRects = Array.from(range.getClientRects());
    const rects = clientRects.map(
      (r) =>
        [
          (r.left - pr.left) / scale,
          (r.top - pr.top) / scale,
          (r.right - pr.left) / scale,
          (r.bottom - pr.top) / scale,
        ] as [number, number, number, number],
    );
    setSelection({ text, page: pageIndex, rects });
    const last = clientRects[clientRects.length - 1];
    if (last) {
      // position the popover in viewport coords, right beside the selection
      // (rendered position:fixed), clamped so it can't run off the right edge
      setPopover({
        x: Math.max(8, Math.min(last.left, window.innerWidth - 330)),
        y: last.bottom + 8,
      });
    }
  }

  if (!current) return null;
  const n = current.n_pages;

  return (
    <div className="pdf-wrap">
      <div className="pdf-toolbar">
        <span className="paper-title" title={current.title}>
          {current.title || "Untitled"}
        </span>
        <div className="zoom">
          <button onClick={() => setScale((s) => Math.max(0.6, s - 0.15))}>−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button onClick={() => setScale((s) => Math.min(3, s + 0.15))}>+</button>
        </div>
        <div className="pdf-disp">
          <button className="pdf-disp-btn" title={uiLang === "zh" ? "显示设置" : "Display settings"} onClick={() => setDispOpen((o) => !o)}>
            👁
          </button>
          {dispOpen && (
            <div className="pdf-disp-pop" onMouseLeave={() => setDispOpen(false)}>
              <label>
                <input
                  type="checkbox"
                  checked={showHl}
                  onChange={(e) => {
                    setShowHl(e.target.checked);
                    localStorage.setItem("gloss.showHl", e.target.checked ? "1" : "0");
                  }}
                />
                {uiLang === "zh" ? "显示批注与高亮" : "Show highlights & annotations"}
              </label>
            </div>
          )}
        </div>
      </div>
      <div className="pdf-scroll" ref={containerRef} onMouseUp={onMouseUp}>
        {Array.from({ length: n }).map((_, i) => {
          const pinfo = pages?.pages[i];
          const scaleFromPdf = pinfo ? scale : scale;
          return (
            <div
              key={i}
              className="pdf-page"
              data-page-index={i}
              ref={(el) => (pageRefs.current[i] = el)}
            >
              <canvas />
              {showHl && (
              <div className="highlight-layer">
                {highlights
                  .filter((h) => h.page === i)
                  .map((h) =>
                    h.rects.map((r, ri) => (
                      <div
                        key={h.id + ri}
                        className="hl"
                        title={h.note || h.category}
                        style={{
                          left: r[0] * scaleFromPdf,
                          top: r[1] * scaleFromPdf,
                          width: (r[2] - r[0]) * scaleFromPdf,
                          height: (r[3] - r[1]) * scaleFromPdf,
                          background: h.color + (h.kind === "auto" ? "66" : "99"),
                        }}
                        onClick={() => useStore.getState().setTab("highlights")}
                      />
                    )),
                  )}
              </div>
              )}
              {flash && flash.page === i && (
                <div className="flash-layer">
                  {flash.rects.map((r, ri) => (
                    <div
                      key={ri}
                      className="flash-rect"
                      style={{
                        left: r[0] * scale,
                        top: r[1] * scale,
                        width: (r[2] - r[0]) * scale,
                        height: (r[3] - r[1]) * scale,
                      }}
                    />
                  ))}
                </div>
              )}
              <div className="textLayer" />
              <div className="page-num">{i + 1}</div>
            </div>
          );
        })}
      </div>
      {popover && (
        <SelectionPopover pos={popover} onClose={() => setPopover(null)} />
      )}
    </div>
  );
}
