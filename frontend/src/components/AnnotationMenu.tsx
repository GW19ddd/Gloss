import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useStore } from "../store";

export interface AnnotationMenuProps {
  x: number;
  y: number;
  /** where the mark came from — shown so deleting the right one is obvious */
  heading: string;
  /** the annotation's own text, quoted and offered for copying */
  text: string;
  onDelete: () => void;
  onClose: () => void;
}

/**
 * The menu a right-click on any PDF mark opens. Every mark Gloss draws — one
 * from the database, note evidence, or something another reader left in the
 * file — gets the same one, so every mark can be removed where it sits.
 */
export function AnnotationMenu({
  x,
  y,
  heading,
  text,
  onDelete,
  onClose,
}: AnnotationMenuProps) {
  const uiLang = useStore((s) => s.uiLang);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y });
  const T = uiLang === "zh"
    ? { del: "删除批注", copy: "复制文本" }
    : { del: "Delete annotation", copy: "Copy text" };

  // Keep the menu on screen when the mark sits near an edge.
  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    setPos({
      x: Math.max(6, Math.min(x, window.innerWidth - box.width - 6)),
      y: Math.max(6, Math.min(y, window.innerHeight - box.height - 6)),
    });
  }, [x, y]);

  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    // The right-click that opened this is still finishing; listening at once
    // would close the menu on that very event.
    const timer = window.setTimeout(
      () => window.addEventListener("mousedown", away),
      0,
    );
    window.addEventListener("keydown", escape);
    window.addEventListener("scroll", onClose, true);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", escape);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose]);

  return (
    <div className="annot-menu" ref={ref} style={{ left: pos.x, top: pos.y }} role="menu">
      <div className="annot-menu-head">{heading}</div>
      {text && <div className="annot-menu-text">{text.slice(0, 240)}</div>}
      <div className="annot-menu-actions">
        {text && (
          <button onClick={() => void navigator.clipboard?.writeText(text)}>
            {T.copy}
          </button>
        )}
        <button
          className="danger"
          onClick={() => {
            onDelete();
            onClose();
          }}
        >
          {T.del}
        </button>
      </div>
    </div>
  );
}
