import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Check, CheckCircle2, Inbox, ListChecks, Loader2, MessageSquare, Plus, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { ACTION_STATUS, CHANNEL_LABELS, actionFields, mergeTimeline, plainReply } from "./copilotModel";

const POLL_MS = 60000;

function ActionCard({ action, onDecided }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const notSent = /^Not (sent|confirmed)/.test(action.verification || "");
  const state = notSent ? { label: "Saved, not sent", tone: "amber" } : ACTION_STATUS[action.status] || ACTION_STATUS.proposed;
  const decide = async (verb) => {
    setBusy(verb);
    setError("");
    try {
      onDecided(await api.post(`/copilot/actions/${action.id}/${verb}/`, {}));
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="rounded-xl p-3" style={{ backgroundColor: C.slip, border: `1px solid ${action.status === "proposed" ? `${C.amber}66` : C.rule}` }}>
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-[13px]" style={{ fontWeight: 700, color: C.ink }}>{action.label}</p>
        <span className="shrink-0 text-[11px]" style={{ fontWeight: 700, color: C[state.tone] }}>{state.label}</span>
      </div>
      {action.target && <p className="mt-1 break-words text-xs" style={{ color: C.inkSoft }}>{action.target}</p>}
      {actionFields(action.body).length > 0 && (
        <dl className="mt-2 space-y-1 text-xs">
          {actionFields(action.body).map((field) => (
            <div key={field.key} className="flex gap-2">
              <dt className="w-28 shrink-0" style={{ color: C.inkSoft }}>{field.label}</dt>
              <dd className="m-0 min-w-0 whitespace-pre-wrap break-words" style={{ color: C.ink, fontWeight: 600 }}>{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {action.status === "proposed" && (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={!!busy} onClick={() => decide("confirm")} className="flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 700, color: C.onAccent, backgroundColor: C.stamp }}>
            {busy === "confirm" ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Confirm
          </button>
          <button type="button" disabled={!!busy} onClick={() => decide("reject")} className="rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 600, color: C.ink, border: `1px solid ${C.ruleStrong}` }}>Reject</button>
        </div>
      )}
      {action.status === "failed" && <p role="alert" className="mt-2 text-xs" style={{ color: C.carbon }}>{action.result}</p>}
      {action.verification && <p className="mt-2 flex items-start gap-1 text-xs" style={{ color: notSent ? C.amber : C.green }}><CheckCircle2 size={13} className="mt-px shrink-0" /><span className="min-w-0 break-words">{action.verification}</span></p>}
      {error && <p role="alert" className="mt-2 text-xs" style={{ color: C.carbon }}>{error}</p>}
    </div>
  );
}

function ChatTab({ status, prefill, onPrefillUsed }) {
  const [conversation, setConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [actions, setActions] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);
  const busyRef = useRef(false);

  const send = useCallback(async (value) => {
    const message = (value ?? "").trim();
    if (!message || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setText("");
    setMessages((rows) => [...rows, { id: `me-${Date.now()}`, role: "user", text: message, created_at: new Date().toISOString() }]);
    try {
      const data = await api.post("/copilot/chat/", { message, conversation: conversation || undefined });
      setConversation(data.conversation);
      setMessages((rows) => [...rows, { id: `ai-${Date.now()}`, role: "assistant", text: data.reply, created_at: new Date().toISOString() }]);
      // shown under the reply they belong to
      const after = new Date(Date.now() + 1).toISOString();
      setActions((rows) => [...rows, ...data.actions.map((action) => ({ ...action, created_at: after }))]);
    } catch (reason) {
      setError(reason.message);
      setText(message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [conversation]);

  useEffect(() => {
    if (!prefill) return;
    onPrefillUsed();
    send(prefill);
  }, [prefill, onPrefillUsed, send]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [messages, actions, busy]);

  const onKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(text);
    }
  };
  const updateAction = (updated) => setActions((rows) => rows.map((row) => (row.id === updated.id ? { ...updated, created_at: row.created_at } : row)));
  const newChat = () => { setConversation(null); setMessages([]); setActions([]); setError(""); };
  const timeline = mergeTimeline(messages, actions);

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {!timeline.length && (
          <div>
            <p className="text-sm" style={{ fontWeight: 700, color: C.ink }}>How can I help?</p>
            <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>I can look things up and prepare work. Nothing changes until you press Confirm.</p>
            <div className="mt-3 space-y-2">
              {(status?.suggestions || []).map((item) => (
                <button key={item} type="button" onClick={() => send(item)} className="block w-full rounded-lg px-3 py-2 text-left text-xs hover:bg-black/5" style={{ fontWeight: 600, color: C.stamp, border: `1px solid ${C.rule}` }}>{item}</button>
              ))}
            </div>
          </div>
        )}
        {timeline.map((row) => (row.kind === "action"
          ? <ActionCard key={`action-${row.item.id}`} action={row.item} onDecided={updateAction} />
          : (
            <div key={row.item.id} className={`flex ${row.item.role === "user" ? "justify-end" : "justify-start"}`}>
              <p className="m-0 max-w-[88%] whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-[13px] leading-5" style={row.item.role === "user" ? { color: C.onAccent, backgroundColor: C.stamp } : { color: C.ink, backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>{row.item.role === "user" ? row.item.text : plainReply(row.item.text)}</p>
            </div>
          )))}
        {busy && <p className="flex items-center gap-2 text-xs" style={{ color: C.inkSoft }} role="status"><Loader2 size={13} className="animate-spin" /> Working…</p>}
        {error && <p role="alert" className="rounded-lg px-3 py-2 text-xs" style={{ color: C.carbon, backgroundColor: `${C.carbon}10` }}>{error}</p>}
        <div ref={endRef} />
      </div>
      <div className="shrink-0 p-3" style={{ borderTop: `1px solid ${C.rule}` }}>
        <div className="flex items-end gap-2 rounded-xl p-1.5" style={{ border: `1px solid ${C.ruleStrong}`, backgroundColor: C.slip }}>
          {timeline.length > 0 && <button type="button" onClick={newChat} aria-label="New chat" title="New chat" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-black/5" style={{ color: C.inkSoft }}><Plus size={16} /></button>}
          <label className="sr-only" htmlFor="copilot-message">Message AI-Staff</label>
          <textarea id="copilot-message" rows={1} value={text} maxLength={4000} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} placeholder="Ask AI-Staff…" className="max-h-28 min-h-9 min-w-0 flex-1 resize-none border-0 bg-transparent px-2 py-2 text-[13px] outline-none" style={{ color: C.ink }} />
          <button type="button" disabled={busy || !text.trim()} onClick={() => send(text)} aria-label="Send" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg disabled:opacity-40" style={{ color: C.onAccent, backgroundColor: C.stamp }}><Send size={15} /></button>
        </div>
      </div>
    </>
  );
}

function InboxItem({ item, onChanged }) {
  const [draft, setDraft] = useState(item.draft);
  const [body, setBody] = useState(item.draft?.body || "");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const run = async (name, work) => {
    setBusy(name);
    setError("");
    try {
      await work();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };
  const write = () => run("draft", async () => {
    const created = await api.post("/copilot/drafts/", { message: item.id });
    setDraft(created);
    setBody(created.body);
  });
  const send = () => run("send", async () => {
    const result = await api.post(`/copilot/drafts/${draft.id}/send/`, { body });
    if (result.delivery_status === "simulated") {
      setError("Saved in the CRM, but not sent: WhatsApp isn't connected yet.");
      return;
    }
    if (result.delivery_status === "failed") {
      setError(`Saved on the thread, but not delivered: ${result.delivery_error || "sending failed"}. Resend it from the rental's chat, or contact the customer directly.`);
      return;
    }
    onChanged();
  });
  const dismiss = () => run("dismiss", async () => {
    await api.post("/copilot/inbox/dismiss/", { message: item.id });
    onChanged();
  });
  return (
    <article className="rounded-xl p-3" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="m-0 min-w-0 truncate text-[13px]" style={{ fontWeight: 700, color: C.ink }}>{item.party_name}</p>
        <span className="shrink-0 text-[11px]" style={{ color: C.inkSoft }}>{CHANNEL_LABELS[item.channel] || item.channel}</span>
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-xs" style={{ color: C.ink }}>{item.body}</p>
      <p className="mt-1 text-[11px]" style={{ color: C.inkSoft }}>{new Date(item.at).toLocaleString()}</p>
      {draft ? (
        <>
          <label className="mt-2 block text-[11px]" style={{ fontWeight: 700, color: C.inkSoft }} htmlFor={`draft-${item.id}`}>Suggested reply: check it before sending</label>
          <textarea id={`draft-${item.id}`} rows={4} value={body} onChange={(event) => setBody(event.target.value)} className="mt-1 w-full resize-y rounded-lg p-2 text-xs outline-none" style={{ color: C.ink, border: `1px solid ${C.ruleStrong}`, backgroundColor: C.slip2 }} />
          {draft.sources?.length > 0 && <p className="mt-1 text-[11px]" style={{ color: C.inkSoft }}>Based on: {draft.sources.map((source) => source.label).join(", ")}</p>}
        </>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-2">
        {draft
          ? <button type="button" disabled={!!busy || !body.trim()} onClick={send} className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 700, color: C.onAccent, backgroundColor: C.stamp }}>{busy === "send" ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Send reply</button>
          : <button type="button" disabled={!!busy} onClick={write} className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 700, color: C.onAccent, backgroundColor: C.stamp }}>{busy === "draft" ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Draft reply</button>}
        {draft && <button type="button" disabled={!!busy} onClick={write} className="rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 600, color: C.ink, border: `1px solid ${C.ruleStrong}` }}>{busy === "draft" ? "Rewriting…" : "Rewrite"}</button>}
        <button type="button" disabled={!!busy} onClick={dismiss} className="rounded-lg px-3 py-2 text-xs disabled:opacity-60" style={{ fontWeight: 600, color: C.inkSoft }}>No reply needed</button>
      </div>
      {error && <p role="alert" className="mt-2 text-xs" style={{ color: C.carbon }}>{error}</p>}
    </article>
  );
}

function InboxTab({ onCount }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const data = await api.get("/copilot/inbox/");
      setRows(data);
      onCount(data.length);
      setError("");
    } catch (reason) {
      setError(reason.message);
    }
  }, [onCount]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
      <p className="m-0 text-xs" style={{ color: C.inkSoft }}>Customer messages waiting for an answer. AI-Staff only suggests a reply; you send it.</p>
      {error && <p role="alert" className="text-xs" style={{ color: C.carbon }}>{error}</p>}
      {rows && !rows.length && <p className="text-xs" style={{ color: C.inkSoft }}>All caught up.</p>}
      {rows?.map((item) => <InboxItem key={item.id} item={item} onChanged={load} />)}
    </div>
  );
}

function TasksTab({ onAsk }) {
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get("/copilot/tasks/").then(setTasks).catch((reason) => setError(reason.message)); }, []);
  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
      <p className="m-0 text-xs" style={{ color: C.inkSoft }}>Work for your role and store right now. Pick one and AI-Staff will take you through it.</p>
      {error && <p role="alert" className="text-xs" style={{ color: C.carbon }}>{error}</p>}
      {tasks && !tasks.length && <p className="text-xs" style={{ color: C.inkSoft }}>Nothing waiting for you.</p>}
      {tasks?.map((task) => (
        <button key={task.title} type="button" onClick={() => onAsk(task.prompt)} className="flex w-full items-center justify-between gap-2 rounded-xl p-3 text-left hover:bg-black/5" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
          <span className="text-[13px]" style={{ fontWeight: 600, color: C.ink }}>{task.title}</span>
          <span className="rounded-full px-2 py-0.5 text-[11px]" style={{ fontWeight: 700, color: C.stamp, backgroundColor: `${C.stamp}14` }}>{task.count}</span>
        </button>
      ))}
    </div>
  );
}

export default function CopilotPanel() {
  const { can, me } = useSession();
  const allowed = !!me && can("copilot.use");
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("chat");
  const [status, setStatus] = useState(null);
  const [inboxCount, setInboxCount] = useState(0);
  const [prefill, setPrefill] = useState("");
  const clearPrefill = useCallback(() => setPrefill(""), []);

  useEffect(() => {
    if (!allowed) return undefined;
    const load = () => api.get("/copilot/status/").then((data) => { setStatus(data); setInboxCount(data.inbox_count); }).catch(() => {});
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [allowed]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!allowed) return null;
  const tabs = [
    { id: "chat", label: "Chat", icon: MessageSquare },
    { id: "tasks", label: "My work", icon: ListChecks },
    ...(status?.can_use_inbox ? [{ id: "inbox", label: "Customers", icon: Inbox, count: inboxCount }] : []),
  ];
  return (
    <>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} aria-label={inboxCount ? `Open AI-Staff, ${inboxCount} customers waiting` : "Open AI-Staff"} className="fixed bottom-5 right-5 z-30 flex h-12 items-center gap-2 rounded-full px-4 text-sm shadow-lg" style={{ fontFamily: F.body, fontWeight: 700, color: C.onAccent, backgroundColor: C.stamp }}>
          <Bot size={18} /> AI-Staff
          {inboxCount > 0 && <span className="rounded-full px-1.5 text-[11px]" style={{ color: C.stamp, backgroundColor: "#FFFFFF" }}>{inboxCount}</span>}
        </button>
      )}
      {/* hidden rather than removed, so closing the panel keeps the conversation */}
      <aside role="dialog" aria-label="AI-Staff" hidden={!open} className={`fixed inset-y-0 right-0 z-40 w-full max-w-[420px] flex-col shadow-2xl ${open ? "flex" : "hidden"}`} style={{ fontFamily: F.body, backgroundColor: C.paper, borderLeft: `1px solid ${C.rule}` }}>
          <header className="flex shrink-0 items-center gap-2 px-4 py-3" style={{ backgroundColor: C.slip, borderBottom: `1px solid ${C.rule}` }}>
            <Bot size={18} style={{ color: C.stamp }} />
            <div className="min-w-0 flex-1">
              <p className="m-0 text-sm" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>AI-Staff</p>
              <p className="m-0 flex items-center gap-1 text-[11px]" style={{ color: C.inkSoft }}><ShieldCheck size={11} /> Works with your role and store access</p>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close AI-Staff" className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-black/5" style={{ color: C.inkSoft }}><X size={18} /></button>
          </header>
          <div role="tablist" className="flex shrink-0" style={{ backgroundColor: C.slip, borderBottom: `1px solid ${C.rule}` }}>
            {tabs.map((item) => {
              const active = tab === item.id;
              const Icon = item.icon;
              return (
                <button key={item.id} type="button" role="tab" aria-selected={active} onClick={() => setTab(item.id)} className="flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs" style={{ fontWeight: 600, color: active ? C.stamp : C.inkSoft, borderBottom: `2px solid ${active ? C.stamp : "transparent"}` }}>
                  <Icon size={14} /> {item.label}{item.count > 0 ? ` (${item.count})` : ""}
                </button>
              );
            })}
          </div>
          {status && !status.enabled && <p role="status" className="m-3 rounded-lg px-3 py-2 text-xs" style={{ color: C.ink, backgroundColor: `${C.amber}14`, border: `1px solid ${C.amber}55` }}>AI-Staff isn't set up yet. Add an AI provider key to the backend settings.</p>}
          {/* kept mounted so switching tabs doesn't lose the conversation */}
          <div className={tab === "chat" ? "flex min-h-0 flex-1 flex-col" : "hidden"}><ChatTab status={status} prefill={prefill} onPrefillUsed={clearPrefill} /></div>
          {tab === "tasks" && <TasksTab onAsk={(prompt) => { setPrefill(prompt); setTab("chat"); }} />}
          {tab === "inbox" && <InboxTab onCount={setInboxCount} />}
      </aside>
    </>
  );
}
