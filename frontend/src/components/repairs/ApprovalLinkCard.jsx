import { useState } from "react";
import { Copy, ExternalLink, Send, X } from "lucide-react";

import { Eyebrow } from "../Atoms";
import { C, F, money } from "../../lib/theme";

// The client approval link, shown right after it is issued (ticket creation or an accepted revision).
export default function ApprovalLinkCard({ approval, title = "Send this to the customer", onClose }) {
  const [note, setNote] = useState("");
  if (!approval) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(approval.url); setNote("Link copied."); } catch { setNote("Copy the link from the box."); }
  };
  return (
    <div className="mt-3 p-3" data-panel style={{ border: `1px solid ${C.green}`, backgroundColor: `${C.green}0D` }}>
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
      <div className={`mt-2 grid gap-2 ${approval.whatsapp_url ? "grid-cols-2" : "grid-cols-1"}`}>
        <button type="button" onClick={copy} className="flex items-center justify-center gap-1 py-2 text-xs" style={{ border: `1px solid ${C.rule}` }}><Copy size={13} /> Copy link</button>
        {approval.whatsapp_url && <a href={approval.whatsapp_url} target="_blank" rel="noreferrer" className="flex items-center justify-center gap-1 py-2 text-xs" style={{ backgroundColor: C.green, color: C.onAccent }}><Send size={13} /> WhatsApp</a>}
      </div>
      {note && <p className="mt-1 flex items-center gap-1 text-xs" style={{ color: C.inkSoft }}><ExternalLink size={11} /> {note}</p>}
    </div>
  );
}
