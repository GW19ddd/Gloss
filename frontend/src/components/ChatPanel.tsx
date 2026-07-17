import { useEffect, useRef, useState } from "react";
import { streamPost } from "../api/client";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

export function ChatPanel() {
  const current = useStore((s) => s.current);
  const action = useStore((s) => s.selectionAction);
  const selection = useStore((s) => s.selection);
  const provider = useStore((s) => s.provider);
  const outputLanguage = useStore((s) => s.outputLanguage);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamed, setStreamed] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMsgs([]), [current?.id]);
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [msgs, streamed]);

  async function send(text: string, selText?: string) {
    if (!text.trim() || busy) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    setMsgs(next);
    setInput("");
    setBusy(true);
    setStreamed("");
    let acc = "";
    await streamPost(
      "/api/chat",
      {
        paper_id: current?.id,
        messages: next,
        selection: selText || null,
        language: outputLanguage,
      },
      {
        onDelta: (d) => {
          acc += d;
          setStreamed(acc);
        },
        onError: (e) => {
          acc += `\n\n_error: ${e}_`;
          setStreamed(acc);
        },
        onDone: () => {},
      },
    );
    setMsgs((m) => [...m, { role: "assistant", content: acc }]);
    setStreamed("");
    setBusy(false);
  }

  // "Ask" from the selection popover.
  useEffect(() => {
    if (action?.kind === "ask") {
      send(`Explain / discuss this selection.`, action.selection.text);
    }
  }, [action?.id]);

  return (
    <div className="panel-body chat">
      <div className="chat-body" ref={bodyRef}>
        {msgs.length === 0 && !streamed && (
          <div className="muted">
            Ask about this paper — methods, results, limitations, or select text and hit “Ask”.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={"msg " + m.role}>
            <div className="msg-role">{m.role === "user" ? "you" : "moonlight"}</div>
            {m.role === "assistant" ? <Markdown text={m.content} /> : <div className="msg-text">{m.content}</div>}
          </div>
        ))}
        {streamed && (
          <div className="msg assistant">
            <div className="msg-role">moonlight</div>
            <Markdown text={streamed} />
          </div>
        )}
        {busy && !streamed && <div className="muted blink">▍ thinking…</div>}
      </div>
      <div className="chat-input">
        {selection?.text && (
          <div className="attached" title={selection.text}>
            ⧉ selection attached ({selection.text.length} chars)
          </div>
        )}
        <textarea
          value={input}
          placeholder={`Message (${provider})…  ⏎ to send`}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input, selection?.text);
            }
          }}
        />
        <button disabled={busy} onClick={() => send(input, selection?.text)}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
