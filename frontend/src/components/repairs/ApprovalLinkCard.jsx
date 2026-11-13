import { useState } from "react";
import { Check, Copy, ExternalLink, Send, X } from "lucide-react";

import { Eyebrow } from "../Atoms";
import { api } from "../../lib/api";
import { C, F, money } from "../../lib/theme";
import { whatsappSendNote } from "../../lib/whatsappDelivery";

// The client approval link, shown right after it is issued. Staff can copy it,
// send it through the WhatsApp API, or open a WhatsApp chat with it filled in.
export default function ApprovalLinkCard({ approval, title = "Send this to the customer", onClose }) {
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [delivery, setDelivery] = useState(approval?.whatsapp_delivery || null);
  if (!approval) return null;
  const apiLive = approval.whatsapp_provider === "meta_cloud" && !!approval.send_path;
  const sent = delivery?.status === "sent";
  const sendNote = whatsappSendNote(delivery);
  const copy = async () => {
    try { await navigator.clipboard.writeText(approval.url); setNote("Link copied."); } catch { setNote("Copy the link from the box."); }
  };
  const send = async () => {
    if (sending || sent) return;
    setSending(true);
    try {
      const result = await api.post(approval.send_path, { approval_url: approval.url });
      setDelivery(result.whatsapp_delivery);
    } catch (error) {
      setDelivery({ status: "failed", reason: error.body?.detail || error.message });
    } finally {
      setSending(false);
    }
  };
  const cell = "flex min-h-[36px] items-center justify-center gap-1 py-2 text-xs";
  return (
    <div className="mt-3 p-3" data-panel style={{ border: `1px solid ${C.green}`, backgroundColor: `color-mix(in srgb, ${C.green} 5%, transparent)` }}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <Eyebrow>{title}</Eyebrow>
          <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            {approval.total != null ? `Estimate ${money(approval.total)} · ` : ""}the secure approval link is valid for 24 hours.
          </p>
        </div>
        {onClose && <button type="button" onClick={onClose} aria-label="Dismiss"><X size={14} style={{ color: C.inkSoft }} /></button>}
      </div>
      <input readOnly value={approval.url} onFocus={(e) => e.target.select()} className="mt-2 w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }} aria-label="Approval link" />
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button type="button" onClick={copy} className={cell} style={{ border: `1px solid ${C.rule}` }}><Copy size={13} /> Copy link</button>
        {apiLive && (
          <button type="button" onClick={send} disabled={sending || sent} className={`${cell} disabled:opacity-70`} style={{ backgroundColor: C.green, color: C.onAccent }}>
            {sent ? <><Check size={13} /> Sent via WhatsApp API</> : <><Send size={13} /> {sending ? "Sending…" : delivery ? "Retry WhatsApp API send" : "Send via WhatsApp API"}</>}
          </button>
        )}
        {approval.whatsapp_url && (
          <a href={approval.whatsapp_url} target="_blank" rel="noreferrer" className={cell} style={apiLive ? { border: `1px solid ${C.rule}` } : { backgroundColor: C.green, color: C.onAccent }}>
            <ExternalLink size={13} /> Open WhatsApp
          </a>
        )}
      </div>
      {sendNote && <p role="status" className="mt-2 text-xs" style={{ fontFamily: F.body, color: sendNote.ok ? C.green : C.carbon, fontWeight: 600 }}>{sendNote.text}</p>}
      {note && <p className="mt-1 flex items-center gap-1 text-xs" style={{ color: C.inkSoft }}><ExternalLink size={11} /> {note}</p>}
    </div>
  );
}
