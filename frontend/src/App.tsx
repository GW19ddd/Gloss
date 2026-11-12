import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import { useStore } from "./store";
import { Library } from "./components/Library";
import { Outline } from "./components/Outline";
import { SidePanel } from "./components/SidePanel";
import { Logo } from "./components/Logo";
import { ProviderSwitcher } from "./components/ProviderSwitcher";
import { ExitConfirmDialog } from "./components/ExitConfirmDialog";
import { PdfViewer } from "./pdf/PdfViewer";
import { startImportJobPolling } from "./importQueue.mjs";

const readNumber = (key: string, fallback: number) => {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

/** Below this the PDF would be squeezed to nothing, so the outline folds away. */
const NARROW_WINDOW = 1180;
/** Never let the panels eat the page: the PDF keeps at least this much width. */
const MIN_PDF_WIDTH = 360;

export default function App() {
  const view = useStore((s) => s.view);
  const current = useStore((s) => s.current);
  const closePaper = useStore((s) => s.closePaper);
  const loadPapers = useStore((s) => s.loadPapers);
  const loadSettings = useStore((s) => s.loadSettings);
  const loadPlugins = useStore((s) => s.loadPlugins);
  const checkProvider = useStore((s) => s.checkProvider);
  const refreshProviderStatuses = useStore((s) => s.refreshProviderStatuses);
  const loadImportJobs = useStore((s) => s.loadImportJobs);
  const openPaper = useStore((s) => s.openPaper);
  const toast = useStore((s) => s.toast);
  const notify = useStore((s) => s.notify);
  const uiLang = useStore((s) => s.uiLang);

  const clampWidth = useCallback(
    (w: number) => Math.min(900, Math.max(320, w)),
    [],
  );
  const [sideWidth, setSideWidth] = useState(() =>
    clampWidth(readNumber("gloss.sideWidth", 440))
  );
  const dragging = useRef(false);

  const clampOutline = useCallback(
    (w: number) => Math.min(340, Math.max(150, w)),
    [],
  );
  const [outlineWidth, setOutlineWidth] = useState(() =>
    clampOutline(readNumber("gloss.outlineWidth", 176))
  );
  const [outlineCollapsed, setOutlineCollapsed] = useState(
    () => localStorage.getItem("gloss.outlineCollapsed") === "1"
  );
  const [focusMode, setFocusMode] = useState(
    () => localStorage.getItem("gloss.focusMode") === "1"
  );
  const [winWidth, setWinWidth] = useState(() => window.innerWidth);

  useEffect(() => {
    // apply the saved theme + PDF night mode on load (controls live in Settings)
    document.documentElement.dataset.theme = localStorage.getItem("gloss.theme") || "midnight";
    document.documentElement.dataset.pdf = localStorage.getItem("gloss.pdfMode") || "light";
    loadPapers();
    loadPlugins();
    loadSettings().then(() => {
      const activeProvider = useStore.getState().provider;
      void checkProvider(activeProvider);
    });
  }, []);

  useEffect(() => startImportJobPolling(loadImportJobs, 1000), [loadImportJobs]);

  // A double-clicked PDF arrives as a paper the backend is holding for us; the
  // endpoint clears it, so a reload lands in the library as usual.
  useEffect(() => {
    void (async () => {
      try {
        const { paper_id } = await api.consumePendingOpen();
        if (paper_id) await openPaper(paper_id);
      } catch {
        /* an older backend, or one that was never handed a file */
      }
    })();
  }, [openPaper]);

  useEffect(() => {
    const timer = window.setInterval(() => void refreshProviderStatuses(), 5000);
    return () => window.clearInterval(timer);
  }, [refreshProviderStatuses]);

  useEffect(() => {
    const onResize = () => setWinWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Fold the outline away on a narrow window — once per crossing only, so a
  // reader who re-opens it on a small screen keeps it.
  const wasNarrow = useRef(winWidth < NARROW_WINDOW);
  useEffect(() => {
    const narrow = winWidth < NARROW_WINDOW;
    if (narrow && !wasNarrow.current) setOutlineCollapsed(true);
    wasNarrow.current = narrow;
  }, [winWidth]);

  useEffect(() => {
    localStorage.setItem("gloss.sideWidth", String(sideWidth));
  }, [sideWidth]);
  useEffect(() => {
    localStorage.setItem("gloss.outlineWidth", String(outlineWidth));
  }, [outlineWidth]);
  useEffect(() => {
    localStorage.setItem("gloss.outlineCollapsed", outlineCollapsed ? "1" : "0");
  }, [outlineCollapsed]);
  useEffect(() => {
    localStorage.setItem("gloss.focusMode", focusMode ? "1" : "0");
  }, [focusMode]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => notify(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  // Panels are fixed-width, so a narrow window has to give the PDF its share
  // back instead of pushing it off the right edge.
  const railWidth = outlineCollapsed ? 28 : outlineWidth;
  const maxSide = Math.max(
    300,
    winWidth - railWidth - (outlineCollapsed ? 0 : 6) - MIN_PDF_WIDTH - 6,
  );
  const effectiveSideWidth = useMemo(
    () => Math.min(sideWidth, maxSide),
    [sideWidth, maxSide],
  );

  const startDrag = () => {
    dragging.current = true;
    document.body.style.userSelect = "none";
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setSideWidth(clampWidth(window.innerWidth - e.clientX));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const startOutlineDrag = () => {
    document.body.style.userSelect = "none";
    const onMove = (e: MouseEvent) => setOutlineWidth(clampOutline(e.clientX));
    const onUp = () => {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const readerClass = [
    "reader",
    focusMode ? "focus" : "",
    winWidth < 1400 ? "compact" : "",
  ].filter(Boolean).join(" ");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={closePaper} style={{ cursor: "pointer" }}>
          <Logo size={20} />
          <span className="brand-name">Gloss</span>
          <span className="brand-zh">旁注</span>
        </div>
        {current && (
          <div className="crumbs">
            <button className="link" onClick={closePaper}>{uiLang === "zh" ? "← 论文库" : "← Library"}</button>
          </div>
        )}
        <div className="spacer" />
        <ProviderSwitcher />
      </header>

      {view === "library" ? (
        <Library />
      ) : (
        <div className={readerClass}>
          {!focusMode && (outlineCollapsed ? (
            <button className="outline-expand" title={uiLang === "zh" ? "显示大纲" : "Show outline"} onClick={() => setOutlineCollapsed(false)}>
              »
            </button>
          ) : (
            <>
              <div className="outline-host" style={{ width: outlineWidth }}>
                <Outline onCollapse={() => setOutlineCollapsed(true)} />
              </div>
              <div className="divider" onMouseDown={startOutlineDrag} />
            </>
          ))}
          <PdfViewer focusMode={focusMode} onToggleFocus={() => setFocusMode((on) => !on)} />
          {!focusMode && (
            <>
              <div className="divider" onMouseDown={startDrag} />
              <div className="side-host" style={{ width: effectiveSideWidth, flex: "0 0 auto", display: "flex" }}>
                <SidePanel />
              </div>
            </>
          )}
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
      <ExitConfirmDialog />
    </div>
  );
}
