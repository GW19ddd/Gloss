import { useState } from "react";

// PDF reading modes — applied via a data-pdf attribute on <html> (like themes).
//   light  正常   — no filter
//   sepia  护眼   — warm paper tint, easier on the eyes
//   dark   夜间   — inverted (dark bg / light text), figures kept via hue-rotate
const MODES: { id: string; label: string; hint: string }[] = [
  { id: "light", label: "Normal", hint: "正常 · white page" },
  { id: "sepia", label: "Sepia", hint: "护眼 · warm, easy on the eyes" },
  { id: "dark", label: "Night", hint: "夜间 · dark page, light text" },
];

export function PdfModeToggle() {
  const [mode, setMode] = useState(() => localStorage.getItem("gloss.pdfMode") || "light");
  function apply(m: string) {
    setMode(m);
    localStorage.setItem("gloss.pdfMode", m);
    document.documentElement.dataset.pdf = m;
  }
  return (
    <div className="seg" role="group" aria-label="PDF reading mode">
      {MODES.map((m) => (
        <button
          key={m.id}
          className={"seg-btn" + (mode === m.id ? " active" : "")}
          title={m.hint}
          onClick={() => apply(m.id)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}
