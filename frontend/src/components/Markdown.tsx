import { useEffect, useRef } from "react";
import { marked } from "marked";
import renderMathInElement from "katex/contrib/auto-render";

marked.setOptions({ breaks: true, gfm: true });

export function Markdown({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    ref.current.innerHTML = marked.parse(text || "") as string;
    try {
      renderMathInElement(ref.current, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
      });
    } catch {
      /* ignore math errors */
    }
  }, [text]);
  return <div className="markdown" ref={ref} />;
}
