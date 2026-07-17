import { useEffect, useRef, useState } from "react";
import { pdfjsLib } from "./pdfSetup";
import { api } from "../api/client";
import { useStore } from "../store";
import { SelectionPopover } from "../components/SelectionPopover";

// Manual text layer: position spans from text items so the browser can select
// them. Selection → PDF-point rects is then derived from client rects / scale.
async function renderTextLayer(page: any, viewport: any, layer: HTMLDivElement) {
  const tc = await page.getTextContent();
  layer.innerHTML = "";
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
    span.style.height = `${fontSize}px`;
    span.style.transform = `scaleX(${item.width && item.str.length ? (item.width * viewport.scale) / (fontSize * 0.5 * item.str.length) : 1})`;
    frag.appendChild(span);
  }
  layer.appendChild(frag);
}

export function PdfViewer() {
  const current = useStore((s) => s.current);
  const pages = useStore((s) => s.pages);
  const highlights = useStore((s) => s.highlights);
  const gotoPage = useStore((s) => s.gotoPage);
  const setGoto = useStore((s) => s.setGoto);
  const setSelection = useStore((s) => s.setSelection);

  const [scale, setScale] = useState(1.35);
  const [rendered, setRendered] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const docRef = useRef<any>(null);
  const [popover, setPopover] = useState<{ x: number; y: number } | null>(null);

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
    (async () => {
      for (let i = 1; i <= doc.numPages; i++) {
        if (cancelled) return;
        const holder = pageRefs.current[i - 1];
        if (!holder) continue;
        const page = await doc.getPage(i);
        const viewport = page.getViewport({ scale });
        holder.style.width = `${viewport.width}px`;
        holder.style.height = `${viewport.height}px`;
        const canvas = holder.querySelector("canvas") as HTMLCanvasElement;
        const textLayer = holder.querySelector(".text-layer") as HTMLDivElement;
        const ctx = canvas.getContext("2d")!;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = viewport.width * dpr;
        canvas.height = viewport.height * dpr;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (textLayer) await renderTextLayer(page, viewport, textLayer);
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
              <div className="text-layer" />
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
