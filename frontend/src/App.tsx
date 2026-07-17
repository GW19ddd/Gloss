import { useEffect, useRef, useState } from "react";
import { useStore } from "./store";
import { Library } from "./components/Library";
import { Outline } from "./components/Outline";
import { SidePanel } from "./components/SidePanel";
import { PdfViewer } from "./pdf/PdfViewer";

export default function App() {
  const view = useStore((s) => s.view);
  const current = useStore((s) => s.current);
  const closePaper = useStore((s) => s.closePaper);
  const loadPapers = useStore((s) => s.loadPapers);
  const loadSettings = useStore((s) => s.loadSettings);
  const provider = useStore((s) => s.provider);
  const toast = useStore((s) => s.toast);
  const notify = useStore((s) => s.notify);

  const clampWidth = (w: number) => Math.min(900, Math.max(320, w));
  const [sideWidth, setSideWidth] = useState(() =>
    clampWidth(Number(localStorage.getItem("moonlight.sideWidth")) || 440)
  );
  const dragging = useRef(false);

  useEffect(() => {
    loadPapers();
    loadSettings();
  }, []);

  useEffect(() => {
    localStorage.setItem("moonlight.sideWidth", String(sideWidth));
  }, [sideWidth]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => notify(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={closePaper} style={{ cursor: "pointer" }}>
          🌙 Moonlight <span className="local">local</span>
        </div>
        {current && (
          <div className="crumbs">
            <button className="link" onClick={closePaper}>← Library</button>
          </div>
        )}
        <div className="spacer" />
        <div className="provider-badge" title="Active AI provider">⚡ {provider}</div>
      </header>

      {view === "library" ? (
        <Library />
      ) : (
        <div className="reader">
          <Outline />
          <PdfViewer />
          <div className="divider" onMouseDown={startDrag} />
          <div className="side-host" style={{ width: sideWidth, flex: "0 0 auto", display: "flex" }}>
            <SidePanel />
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
