import { useEffect, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

interface Msg {
  role: "user" | "assistant";
  content: string;
}
interface Chat {
  id: string;
  title: string;
  created_at: number;
}

// module-scoped so a given "ask" selection is sent exactly once, even across remounts
let lastAskId = 0;

function fmtTime(ts: number | undefined, uiLang: "en" | "zh") {
  if (!ts) return uiLang === "zh" ? "新会话" : "New";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// user message bubble — long content (e.g. a pasted equation) is collapsible
function UserMsg({ content }: { content: string }) {
  const uiLang = useStore((s) => s.uiLang);
  const [open, setOpen] = useState(false);
  const long = content.length > 260;
  const shown = open || !long ? content : content.slice(0, 240) + " …";
  return (
    <div className="msg-text">
      {shown}
      {long && (
        <button className="msg-more" onClick={() => setOpen((o) => !o)}>
          {open ? (uiLang === "zh" ? "收起" : "Show less") : uiLang === "zh" ? "展开全文" : "Show more"}
        </button>
      )}
    </div>
  );
}

export function ChatPanel() {
  const current = useStore((s) => s.current);
  const action = useStore((s) => s.selectionAction);
  const selection = useStore((s) => s.selection);
  const provider = useStore((s) => s.provider);
  const outputLanguage = useStore((s) => s.outputLanguage);
  const uiLang = useStore((s) => s.uiLang);
  const T = {
    en: {
      sessionsTitle: "Chat sessions for this paper",
      newTitle: "Start a new conversation",
      newChat: "＋ New chat",
      delTitle: "Delete this session",
      delConfirm: "Delete this session and all its messages?",
      empty:
        'Ask about this paper — methods, results, limitations, or select text in the PDF / any panel and hit "Add to chat".',
      thinking: "▍ thinking…",
      session: (n: number, t: string) => `Session ${n} · ${t}`,
    },
    zh: {
      sessionsTitle: "本论文的会话",
      newTitle: "新建会话",
      newChat: "＋ 新会话",
      delTitle: "删除当前会话",
      delConfirm: "删除当前会话及其全部消息？",
      empty: "就这篇论文提问 — 方法、结果、局限，或在 PDF / 各面板里选中内容点“加入会话”。",
      thinking: "▍ 思考中…",
      session: (n: number, t: string) => `会话 ${n} · ${t}`,
    },
  }[uiLang];
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamed, setStreamed] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const setSelection = useStore((s) => s.setSelection);

  async function loadMessages(cid: string) {
    try {
      const { messages } = await api.getChatMessages(cid);
      setMsgs(messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.content })));
    } catch {
      setMsgs([]);
    }
  }
  async function refreshChats() {
    if (!current?.id) return;
    try {
      const { chats } = await api.listChats(current.id);
      setChats(chats);
    } catch {
      /* ignore */
    }
  }

  // Load this paper's chat sessions + the most recent one's messages.
  useEffect(() => {
    let cancelled = false;
    setMsgs([]);
    setChats([]);
    setChatId(null);
    if (!current?.id) return;
    (async () => {
      try {
        let list = (await api.listChats(current.id)).chats as Chat[];
        if (!list.length) {
          const c = await api.createChat(current.id);
          list = [{ id: c.id, title: "Chat", created_at: Date.now() / 1000 }];
        }
        if (cancelled) return;
        setChats(list);
        setChatId(list[0].id);
        await loadMessages(list[0].id);
      } catch {
        /* history unavailable */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [current?.id]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [msgs, streamed]);

  async function newChat() {
    if (!current?.id || busy) return;
    try {
      const c = await api.createChat(current.id);
      setChatId(c.id);
      setMsgs([]);
      await refreshChats();
    } catch {
      /* ignore */
    }
  }
  async function switchChat(cid: string) {
    if (cid === chatId || busy) return;
    setChatId(cid);
    await loadMessages(cid);
  }
  async function deleteCurrentChat() {
    if (!current?.id || !chatId || busy) return;
    if (!confirm(T.delConfirm)) return;
    try {
      await api.deleteChat(chatId);
      const list = (await api.listChats(current.id)).chats as Chat[];
      if (list.length) {
        setChats(list);
        setChatId(list[0].id);
        await loadMessages(list[0].id);
      } else {
        const c = await api.createChat(current.id);
        setChats([{ id: c.id, title: "Chat", created_at: Date.now() / 1000 }]);
        setChatId(c.id);
        setMsgs([]);
      }
    } catch {
      /* ignore */
    }
  }

  async function send(text: string, selText?: string) {
    if (!text.trim() || busy) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    const firstMsg = msgs.length === 0;
    setMsgs(next);
    setInput("");
    setBusy(true);
    setStreamed("");
    let cid = chatId;
    if (!cid && current?.id) {
      try {
        cid = (await api.createChat(current.id)).id;
        setChatId(cid);
      } catch {
        /* persistence unavailable */
      }
    }
    let acc = "";
    await streamPost(
      "/api/chat",
      {
        paper_id: current?.id,
        chat_id: cid,
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
    if (firstMsg) refreshChats(); // keep the session list fresh
  }

  // "Ask" from a selection popover (PDF or a side panel). Fire once per selection.
  // The selected content is embedded in the visible message so you can see exactly
  // what was asked (not just a generic instruction).
  useEffect(() => {
    if (action?.kind === "ask" && action.id !== lastAskId) {
      lastAskId = action.id;
      const sel = action.selection.text;
      const zh = outputLanguage.startsWith("中文");
      const prefix = zh ? "解释并讨论我选中的这段内容：" : "Explain and discuss this selected content:";
      send(`${prefix}\n\n${sel}`).finally(() => {
        setSelection(null); // clear the attached selection so you can keep typing freely
        inputRef.current?.focus();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action?.id]);

  return (
    <div className="panel-body chat">
      <div className="chat-head">
        <select
          className="chat-session"
          value={chatId || ""}
          onChange={(e) => switchChat(e.target.value)}
          disabled={busy}
          title={T.sessionsTitle}
        >
          {chats.map((c, i) => (
            <option key={c.id} value={c.id}>
              {T.session(chats.length - i, fmtTime(c.created_at, uiLang))}
            </option>
          ))}
        </select>
        <button className="chat-new" onClick={newChat} disabled={busy} title={T.newTitle}>
          {T.newChat}
        </button>
        <button className="chat-del" onClick={deleteCurrentChat} disabled={busy || !chatId} title={T.delTitle}>
          🗑
        </button>
      </div>
      <div className="chat-body" ref={bodyRef}>
        {msgs.length === 0 && !streamed && <div className="muted">{T.empty}</div>}
        {msgs.map((m, i) => (
          <div key={i} className={"msg " + m.role}>
            <div className="msg-role">{m.role === "user" ? "you" : "gloss"}</div>
            {m.role === "assistant" ? <Markdown text={m.content} /> : <UserMsg content={m.content} />}
          </div>
        ))}
        {streamed && (
          <div className="msg assistant">
            <div className="msg-role">gloss</div>
            <Markdown text={streamed} />
          </div>
        )}
        {busy && !streamed && <div className="muted blink">{T.thinking}</div>}
      </div>
      <div className="chat-input">
        {selection?.text && (
          <div className="attached" title={selection.text}>
            ⧉ selection attached ({selection.text.length} chars)
          </div>
        )}
        <textarea
          ref={inputRef}
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
