import { useEffect, useRef } from "react";
import { marked } from "marked";
import katex from "katex";

marked.setOptions({ breaks: true, gfm: true });

// Render math BEFORE markdown: marked would otherwise mangle LaTeX (underscores
// become <em>, backslashes get altered), leaving raw $$...$$ in the output. We
// pull every math span out, render it with KaTeX, stash a neutral placeholder,
// run marked, then splice the rendered HTML back in.
export function renderWithMath(text: string): string {
  const store: string[] = [];
  const stash = (tex: string, display: boolean) => {
    let html: string;
    try {
      html = katex.renderToString(tex.trim(), { displayMode: display, throwOnError: false });
    } catch {
      html = display ? `$$${tex}$$` : `$${tex}$`;
    }
    store.push(html);
    return `%%KTX${store.length - 1}%%`;
  };

  let s = text;
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => stash(tex, true)); // $$ ... $$
  s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_m, tex) => stash(tex, true)); // \[ ... \]
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_m, tex) => stash(tex, false)); // \( ... \)
  s = s.replace(/\$([^$\n]+?)\$/g, (_m, tex) => stash(tex, false)); // $ ... $

  // Provenance tags the note writer emits: a chip is easier to scan than four
  // brackets, and it keeps the reader from mistaking an inference for a quote.
  s = s.replace(/\[原文\]/g, '<span class="prov prov-source">原文</span>');
  s = s.replace(/\[AI 解读\]/g, '<span class="prov prov-ai">AI 解读</span>');
  s = s.replace(/\[待核实\]/g, '<span class="prov prov-check">待核实</span>');
  s = s.replace(/\[外部\]/g, '<span class="prov prov-out">外部</span>');
  s = s.replace(/\[source\]/g, '<span class="prov prov-source">source</span>');
  s = s.replace(/\[AI reading\]/g, '<span class="prov prov-ai">AI reading</span>');
  s = s.replace(/\[unverified\]/g, '<span class="prov prov-check">unverified</span>');

  let html = marked.parse(s) as string;
  html = html.replace(/%%KTX(\d+)%%/g, (_m, i) => store[Number(i)] ?? "");
  return html;
}

export function Markdown({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    try {
      ref.current.innerHTML = renderWithMath(text || "");
    } catch {
      ref.current.textContent = text || "";
    }
  }, [text]);
  return <div className="markdown" ref={ref} />;
}
