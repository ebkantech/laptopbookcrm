import { useEffect, useRef, useState } from "react";
import { Copy, KeyRound, Link2, Mail, MessageCircle, Pencil, Send, X } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Spinner } from "./Atoms";
import { LinkActionsMenu } from "./parties/PartyActions";
import { copyText } from "../lib/copyText";

// Links in a message, without trailing punctuation.
const linksIn = (body) => Array.from(new Set((body.match(/https?:\/\/[^\s]+/g) || []).map((url) => url.replace(/[),.!]+$/, ""))));
// Portal code emails are stored with the code masked. For staff with
// portal.manage the parent passes `otpByMessage` (from the encrypted,
// permission-checked /portal-otps/ endpoint): each entry shows ITS OWN code
// and status for good -- used, expired or superseded codes stay readable,
// but only the backend's hashed current code can ever sign a customer in.
const OTP_MASK = "******";
const OTP_RE = /^\d{6}$/;
const OTP_STATUS = { active: "Active", used: "Used", superseded: "Superseded", locked: "Locked", expired: "Expired", revoked: "Revoked" };
// WhatsApp Cloud API outcome of an outgoing message. "Sent" is Meta
// accepting it; only Meta's delivery webhook makes it Delivered/Read.
const DELIVERY = {
  sending: { label: "Sending…", tone: "soft" },
  sent: { label: "✓ Sent to WhatsApp API", tone: "soft" },
  delivered: { label: "✓✓ Delivered", tone: "ok" },
  read: { label: "✓✓ Read", tone: "read" },
  failed: { label: "Failed", tone: "bad", retry: "Retry" },
  unknown: { label: "Outcome unknown — it may already have been sent", tone: "warn", retry: "Send again anyway", confirm: true },
  simulated: { label: "Not sent — WhatsApp API is in simulation mode", tone: "soft", retry: "Retry" },
};
// SMTP outcome of an outgoing email. "Sent" is the mail server accepting
// it -- there's no inbox confirmation, and no resend (write it again).
const EMAIL_DELIVERY = {
  sending: { label: "Sending…", tone: "soft" },
  sent: { label: "✓ Accepted by mail server", tone: "soft" },
  failed: { label: "Email not sent", tone: "bad" },
};

export function PartyThread({ partyId, messages, onChanged, onHidden, defaultChannel = "whatsapp", otpByMessage = {} }) {
  const { can } = useSession();
  const canManage = can("parties.manage");
  const [channel, setChannel] = useState(defaultChannel);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState("");
  const [deleteId, setDeleteId] = useState(null);
  const [notice, setNotice] = useState({});
  const [error, setError] = useState("");
  const draftRef = useRef(null);
  const messagesRef = useRef(null);
  const submitLock = useRef(false);
  const [retryingId, setRetryingId] = useState(null);
  const meta = { whatsapp: { color: C.green, icon: MessageCircle }, email: { color: C.blue, icon: Mail } };
  const sendColor = channel === "whatsapp" ? "#25D366" : "#2563EB";
  const shown = messages.filter((message) => message.channel === channel);
  const otpEntry = (message) => (message.channel === "email" && message.body.includes(OTP_MASK) && otpByMessage[message.id]) || null;
  const otpFor = (message) => {
    const entry = otpEntry(message);
    return entry && OTP_RE.test(entry.otp || "") ? entry.otp : "";
  };
  const statusOf = (message) => OTP_STATUS[otpEntry(message)?.status] || "";
  const bodyOf = (message) => {
    const otp = otpFor(message);
    return otp ? message.body.replace(OTP_MASK, otp) : message.body;
  };

  useEffect(() => {
    const input = draftRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
  }, [draft]);

  useEffect(() => {
    if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [partyId, channel, shown.length]);

  const flash = (id, value) => {
    setNotice((current) => ({ ...current, [id]: value }));
    window.setTimeout(() => setNotice((current) => current[id] === value ? { ...current, [id]: "" } : current), 2000);
  };
  const copy = async (message) => {
    try { await copyText(bodyOf(message)); flash(message.id, "Copied"); }
    catch (reason) { flash(message.id, reason.message || "Couldn't copy this message."); }
  };
  const copyLink = async (message, link) => {
    try { await copyText(link); flash(message.id, "Copied"); }
    catch (reason) { flash(message.id, reason.message || "Couldn't copy this link."); }
  };
  const copyOtp = async (message, otp) => {
    try { await copyText(otp); flash(message.id, "Copied"); }
    catch (reason) { flash(message.id, reason.message || "Couldn't copy this code."); }
  };
  // One-tap copy buttons under a message: the live OTP in its email, the link(s) in a WhatsApp message.
  const quickCopies = (message) => {
    if (channel === "email") {
      const otp = otpFor(message);
      const status = statusOf(message);
      return otp ? [{ key: "otp", label: `Copy OTP ${otp}${status ? ` · ${status}` : ""}`, icon: KeyRound, run: () => copyOtp(message, otp) }] : [];
    }
    return linksIn(message.body).map((link, index) => ({ key: link, label: `Copy link${index ? ` ${index + 1}` : ""}`, icon: Link2, run: () => copyLink(message, link) }));
  };
  const actionError = (reason, action) => {
    if (reason.status === 401) return "Your session expired. Sign in again, then retry this action.";
    if (reason.status === 403) {
      if (reason.body?.code === "csrf_failed") return "Django blocked this request during CSRF validation. Reload the CRM and retry; if it continues, check the development server origins.";
      if (action === "hide") return "Your account needs Parties view permission to hide this message.";
      return "Your account needs Parties management permission to edit or delete this shared message.";
    }
    if (reason.status === 404) return "This message or customer is no longer available. Refresh the customer record.";
    if (reason.status === 409) return reason.body?.detail || "This historical message cannot be changed.";
    return reason.body?.detail || reason.message || `Couldn't ${action} message. Try again.`;
  };
  const saveDraft = async () => {
    if (!draft.trim() || saving || submitLock.current || !canManage) return;
    submitLock.current = true;
    setSaving(true); setError("");
    try {
      const saved = await api.post(`/parties/${partyId}/messages/`, { channel, body: draft });
      onChanged(saved); setDraft("");
      // saved either way; say so when WhatsApp didn't take it
      if (saved.delivery_status === "failed" || saved.delivery_status === "unknown") setError(`Saved in the CRM, but not confirmed ${saved.channel === "email" ? "by the mail server" : "on WhatsApp"}: ${saved.delivery_error || "sending failed"}.`);
    } catch (reason) {
      setError(reason.status === 401 ? "Your session expired. Sign in again, then retry." : reason.status === 403 && reason.body?.code === "csrf_failed" ? "Django blocked this request during CSRF validation. Reload the CRM and retry; if it continues, check the development server origins." : reason.status === 403 ? "Your role needs Parties management permission to add CRM messages." : reason.body?.detail || reason.message || "Couldn't save message.");
    } finally { submitLock.current = false; setSaving(false); }
  };
  const retrySend = async (message) => {
    if (retryingId) return;
    setRetryingId(message.id); setError("");
    try {
      const updated = await api.post(`/parties/${partyId}/messages/${message.id}/retry/`, { confirm: !!DELIVERY[message.delivery_status]?.confirm });
      onChanged(updated);
    } catch (reason) {
      setError(reason.status === 403 ? "Your role needs Parties management permission to resend messages." : reason.body?.detail || reason.message || "Couldn't resend the message.");
    } finally { setRetryingId(null); }
  };
  const deliveryLine = (message) => {
    const states = { whatsapp: DELIVERY, email: EMAIL_DELIVERY }[message.channel];
    const state = states && message.direction === "out" && !message.is_deleted && states[message.delivery_status];
    if (!state) return null;
    const color = { ok: C.green, read: C.blue, bad: C.carbon, warn: C.amber, soft: C.inkSoft }[state.tone];
    return <div className="mt-0.5 flex flex-wrap items-center justify-end gap-x-2 gap-y-0.5 text-[10px]" style={{ fontFamily: F.body, color }}>
      <span role="status" className="text-right" style={{ fontWeight: 600 }}>{state.label}{message.delivery_status === "failed" && message.delivery_error ? `: ${message.delivery_error}` : ""}</span>
      {state.retry && canManage && <button type="button" onClick={() => retrySend(message)} disabled={!!retryingId} className="rounded-full px-2 py-0.5 disabled:opacity-50" style={{ border: `1px solid ${color}66`, color, fontWeight: 700 }}>{retryingId === message.id ? "Sending…" : state.retry}</button>}
    </div>;
  };
  const handleComposerKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      saveDraft();
    }
  };
  const saveEdit = async (message) => {
    if (editSaving || !editText.trim()) return setError("Message content cannot be empty.");
    if (editText === message.body) { setEditingId(null); setEditText(""); setError(""); return; }
    setEditSaving(true);
    setError("");
    try {
      const updated = await api.patch(`/parties/${partyId}/messages/${message.id}/`, { body: editText });
      onChanged(updated); setEditingId(null); setEditText("");
    } catch (reason) { setError(actionError(reason, "edit")); }
    finally { setEditSaving(false); }
  };
  const hideForMe = async (message) => {
    if (deleteBusy || !message) return;
    setDeleteBusy(true); setError("");
    try { await api.post(`/parties/${partyId}/messages/${message.id}/hide/`, {}); onHidden(message.id); setDeleteId(null); }
    catch (reason) { setError(actionError(reason, "hide")); }
    finally { setDeleteBusy(false); }
  };
  const deleteForEveryone = async (message) => {
    if (deleteBusy || !message) return;
    setDeleteBusy(true); setError("");
    try {
      const deleted = await api.post(`/parties/${partyId}/messages/${message.id}/delete-for-everyone/`, {});
      onChanged(deleted); setDeleteId(null);
    } catch (reason) { setError(actionError(reason, "delete")); }
    finally { setDeleteBusy(false); }
  };

  return <div data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
    <div className="flex" style={{ borderBottom: `1px solid ${C.rule}` }}>
      {["whatsapp", "email"].map((key) => { const item = meta[key]; const active = channel === key; return <button key={key} type="button" onClick={() => { setChannel(key); setError(""); }} className="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: active ? item.color : C.inkSoft, backgroundColor: active ? `${item.color}17` : "transparent", borderBottom: `2px solid ${active ? item.color : "transparent"}` }}><item.icon size={13} />{key === "whatsapp" ? "WhatsApp" : "Email"}</button>; })}
    </div>
    <div ref={messagesRef} className="space-y-2 px-3 py-3" style={{ maxHeight: 260, overflowY: "auto", overscrollBehavior: "contain" }}>
      {shown.map((message) => <div key={message.id} className={`group min-w-0 ${message.direction === "in" ? "pr-1 sm:pr-8" : "pl-1 text-right sm:pl-8"}`}>
        {editingId === message.id ? <div className="w-full rounded-xl p-2 text-left" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
          <textarea value={editText} onChange={(event) => setEditText(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape" && !editSaving) { setEditingId(null); setEditText(""); setError(""); } }} rows={3} autoFocus aria-label="Edit saved message" className="w-full min-w-0 resize-y rounded-lg p-2 text-xs outline-none focus:ring-2 focus:ring-blue-400/40" style={{ color: C.ink, background: C.slip2, border: `1px solid ${C.rule}` }} />
          <div className="mt-2 flex justify-end gap-2"><button type="button" disabled={editSaving} onClick={() => { setEditingId(null); setEditText(""); setError(""); }} className="rounded-lg px-3 py-2 text-xs disabled:opacity-50" style={{ color: C.inkSoft }}>Cancel</button><button type="button" disabled={editSaving || !editText.trim()} onClick={() => saveEdit(message)} className="rounded-lg px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" style={{ background: C.stamp }}>{editSaving ? "Saving…" : "Save"}</button></div>
        </div> : <div className={`flex items-start gap-1 ${message.direction === "out" ? "justify-end" : "justify-start"}`}>
          <p className="inline-block max-w-[calc(100%-2.5rem)] whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, color: message.is_deleted ? C.inkSoft : message.direction === "out" ? C.onAccent : C.ink, backgroundColor: message.is_deleted ? C.slip : message.direction === "out" ? meta[channel].color : C.slip, border: `1px solid ${message.direction === "in" || message.is_deleted ? C.rule : "transparent"}` }}>{bodyOf(message)}</p>
          {!message.is_deleted && <span className="shrink-0 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100"><LinkActionsMenu label={`${channel === "email" ? "Email" : "WhatsApp"} message actions`} items={channel === "email" ? [
            { label: "Copy message", icon: Copy, onSelect: () => copy(message) },
            ...(otpFor(message) ? [{ label: "Copy OTP only", icon: KeyRound, onSelect: () => copyOtp(message, otpFor(message)) }] : []),
          ] : [
            { label: "Copy message", icon: Copy, onSelect: () => copy(message) },
            ...linksIn(message.body).map((link, index) => ({ label: `Copy link only${index ? ` ${index + 1}` : ""}`, icon: Link2, onSelect: () => copyLink(message, link) })),
            ...(message.is_editable && !["sending", "unknown"].includes(message.delivery_status) ? [{ label: canManage ? "Edit" : "Edit (requires permission)", icon: Pencil, disabled: !canManage, onSelect: () => { setEditingId(message.id); setEditText(message.body); setError(""); } }] : [{ label: "Edit unavailable for historical message", icon: Pencil, disabled: true, onSelect: () => {} }]),
            { label: "Delete…", icon: X, danger: true, onSelect: () => { setDeleteId(message.id); setError(""); } },
          ]} /></span>}
        </div>}
        {!message.is_deleted && editingId !== message.id && quickCopies(message).length > 0 && <div className={`mt-1 flex flex-wrap gap-1 ${message.direction === "out" ? "justify-end" : "justify-start"}`}>
          {quickCopies(message).map(({ key, label, icon: Icon, run }) => <button key={key} type="button" onClick={run} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] hover:bg-black/5" style={{ fontFamily: F.body, fontWeight: 600, color: meta[channel].color, border: `1px solid ${meta[channel].color}55` }}><Icon size={11} />{label}</button>)}
        </div>}
        {deliveryLine(message)}
        <div className={`mt-0.5 flex items-center gap-1 text-[10px] ${message.direction === "out" ? "justify-end" : "justify-start"}`} style={{ fontFamily: F.mono, color: C.inkSoft }}>
          <span>{new Date(message.at).toLocaleString()}</span>{message.edited_at && !message.is_deleted && <span aria-label="Edited">· edited</span>}
          {notice[message.id] && <span role="status" style={{ color: notice[message.id] === "Copied" ? C.green : C.carbon }}>· {notice[message.id]}</span>}
        </div>
      </div>)}
      {!shown.length && <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No saved {channel === "whatsapp" ? "WhatsApp" : "email"} messages yet.</p>}
    </div>
    {deleteId && channel === "whatsapp" && <div role="alertdialog" aria-modal="false" className="mx-3 mb-3 rounded-xl p-3" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
      <p className="text-xs font-semibold" style={{ color: C.ink }}>Delete this saved message?</p><p className="mt-1 text-[11px]" style={{ color: C.inkSoft }}>This only changes the CRM record view. It cannot recall a delivered WhatsApp.</p>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2"><button type="button" disabled={deleteBusy} onClick={() => hideForMe(shown.find((message) => message.id === deleteId))} className="rounded-lg px-2 py-2 text-xs font-semibold disabled:opacity-50" style={{ border: `1px solid ${C.rule}`, color: C.ink }}>{deleteBusy ? "Working…" : "Delete for me"}</button><button type="button" disabled={deleteBusy || !canManage} title={!canManage ? "Requires Parties management permission" : undefined} onClick={() => deleteForEveryone(shown.find((message) => message.id === deleteId))} className="rounded-lg px-2 py-2 text-xs font-semibold text-white disabled:opacity-50" style={{ background: C.carbon }}>{!canManage ? "Delete for everyone (no permission)" : deleteBusy ? "Working…" : "Delete for everyone"}</button><button type="button" disabled={deleteBusy} onClick={() => setDeleteId(null)} className="rounded-lg px-2 py-2 text-xs disabled:opacity-50 sm:col-span-2" style={{ color: C.inkSoft }}>Cancel</button></div>
    </div>}
    <div className="px-3 pb-3">
      <label className="sr-only" htmlFor={`message-draft-${partyId}`}>{channel === "whatsapp" ? "New WhatsApp message to the customer" : "New email CRM message"}</label>
      <div className="flex min-w-0 items-end gap-2 rounded-full px-2 py-1.5 transition-shadow focus-within:ring-2" style={{ border: `1px solid ${C.rule}`, background: C.slip, "--tw-ring-color": `${sendColor}55` }}>
        <textarea ref={draftRef} id={`message-draft-${partyId}`} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleComposerKeyDown} rows={1} disabled={!canManage} placeholder={channel === "whatsapp" ? "Type a message..." : "Type an email message..."} aria-describedby={!canManage ? `message-permission-${partyId}` : undefined} className="max-h-[132px] min-h-[34px] min-w-0 flex-1 resize-none appearance-none border-0 bg-transparent px-2 py-2 text-xs leading-5 outline-none shadow-none disabled:cursor-not-allowed disabled:opacity-60" style={{ fontFamily: F.body, color: C.ink, border: "none", boxShadow: "none", outline: "none", background: "transparent" }} />
        <button type="button" onClick={saveDraft} disabled={!canManage || !draft.trim() || saving} aria-label={saving ? "Sending message" : "Send message"} title="Send message" className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white transition duration-150 hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40" style={{ background: sendColor }}><Send size={15} className={saving ? "animate-pulse" : ""} /></button>
      </div>
      <div className="mt-1 flex min-h-4 flex-wrap items-center justify-between gap-x-2 gap-y-1 px-1"><span id={`message-permission-${partyId}`} className="text-[10px]" style={{ color: C.inkSoft }}>{!canManage ? "Parties management permission required" : channel === "whatsapp" ? (saving ? "Sending to WhatsApp…" : "Enter to send on WhatsApp · Shift+Enter for a new line") : saving ? "Saving to CRM…" : "Enter to send · Shift+Enter for a new line · CRM only"}</span>{error && <span role="alert" className="text-right text-[10px]" style={{ color: C.carbon }}>{error}</span>}</div>
    </div>
  </div>;
}

export function PartyChatModal({ partyId, partyName, onClose }) {
  const { can } = useSession();
  const canSeeOtp = can("portal.manage");
  const [messages, setMessages] = useState(null);
  const [otpByMessage, setOtpByMessage] = useState({});
  useEffect(() => { api.get(`/parties/${partyId}/`).then((party) => setMessages(party.messages)); }, [partyId]);
  // same permission-checked source as the Parties page: code emails show their digits only for portal.manage
  useEffect(() => {
    if (!canSeeOtp) return undefined;
    let alive = true;
    api.get(`/parties/${partyId}/portal-otps/`).then((data) => {
      if (!alive) return;
      const byMessage = {};
      (data.otps || []).forEach((row) => {
        if (row.message_id) byMessage[row.message_id] = { otp: OTP_RE.test(row.otp || "") ? row.otp : "", status: row.status };
      });
      setOtpByMessage(byMessage);
    }).catch(() => {}); // 503: display not configured -- entries stay masked
    return () => { alive = false; };
  }, [partyId, canSeeOtp]);
  const update = (message) => setMessages((list) => list.some((item) => item.id === message.id) ? list.map((item) => item.id === message.id ? message : item) : [...list, message]);
  return <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
    <div className="w-full max-w-sm p-5" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(event) => event.stopPropagation()}>
      <div className="flex items-center justify-between"><div><p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>Chat with</p><p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{partyName}</p></div><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button></div>
      <div className="mt-3">{messages === null ? <Spinner /> : <PartyThread partyId={partyId} messages={messages} otpByMessage={otpByMessage} onChanged={update} onHidden={(id) => setMessages((list) => list.filter((message) => message.id !== id))} />}</div>
    </div>
  </div>;
}
