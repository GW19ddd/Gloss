import { useState } from "react";

// PDF night mode — inverts the rendered page (dark bg, light text) via a CSS
// filter on the canvas. Applied through a data-pdf attribute on <html>, like themes.
export function PdfModeToggle() {
  const [dark, setDark] = useState(() => localStorage.getItem("gloss.pdfDark") === "1");
  function apply(v: boolean) {
    setDark(v);
    localStorage.setItem("gloss.pdfDark", v ? "1" : "0");
    document.documentElement.dataset.pdf = v ? "dark" : "light";
  }
  return (
    <label className="pdf-mode-toggle" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
      <input type="checkbox" checked={dark} onChange={(e) => apply(e.target.checked)} />
      <span>PDF 夜间模式（暗色反色）</span>
    </label>
  );
}
