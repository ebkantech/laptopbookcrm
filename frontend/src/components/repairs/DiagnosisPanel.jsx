import { useState } from "react";
import { CheckCircle2, Stethoscope } from "lucide-react";

import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import ManualLines from "./ManualLines";
import ApprovalLinkCard from "./ApprovalLinkCard";
import { cleanLines, validatePricing } from "./bookingModel";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

// Repair staff report back after looking at the device: the estimate holds, or it needs to change (-> Admin).
export default function DiagnosisPanel({ ticket, canWork, canApprove, onChanged }) {
  const [note, setNote] = useState("");
  const [changing, setChanging] = useState(false);
  const [lines, setLines] = useState(() => (ticket.current_estimate?.lines || []).map((l) => ({ description: l.description, quantity: l.quantity, unit_price: l.unit_price, unit_cost: l.unit_cost ?? "" })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [approval, setApproval] = useState(null);

  if (!["Received", "Diagnosing"].includes(ticket.status) && !ticket.diagnosed_at) return null;

  const submit = async (estimateOk) => {
    setError("");
    if (!note.trim()) return setError("Write what you found.");
    if (!estimateOk) {
      const problem = validatePricing({ lines, payment: "full", needLines: true });
      if (problem) return setError(problem);
    }
    setBusy(true);
    try {
      const data = await api.post(`/tickets/${ticket.id}/diagnose/`, { note: note.trim(), estimate_ok: estimateOk, ...(estimateOk ? {} : { lines: cleanLines(lines) }) });
      if (data.approval) setApproval(data.approval);
      onChanged(data.ticket);
    } catch (e) {
      setError(e.body?.detail || e.body?.note?.[0] || e.body?.lines?.[0] || e.message);
    } finally { setBusy(false); }
  };

  return (
    <section className="mt-3 p-3" data-panel style={{ border: `1px solid ${ticket.awaiting_diagnosis ? C.amber : C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>Diagnosis</Eyebrow>
        {ticket.diagnosed_at ? <Pill color={C.green}>Reported</Pill> : ticket.awaiting_diagnosis ? <Pill color={C.amber}>Waiting for {ticket.assigned_to_name}</Pill> : <Pill color={C.inkSoft}>Not reported</Pill>}
      </div>

      {ticket.diagnosed_at && (
        <p className="mt-2 flex items-start gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
          <CheckCircle2 size={14} style={{ color: C.green, flexShrink: 0 }} />
          <span>{ticket.diagnosed_by_name || "Staff"} · {fmt(ticket.diagnosed_at)} — {ticket.diagnosis_note}</span>
        </p>
      )}

      {ticket.awaiting_diagnosis && !canWork && (
        <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Work can start once {ticket.assigned_to_name} reports their diagnosis.</p>
      )}

      {ticket.awaiting_diagnosis && canWork && (
        <div className="mt-2 space-y-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000} placeholder="What did you find? What needs to be done?" className="w-full px-2 py-1.5 text-sm" style={{ border: `1px solid ${C.rule}` }} aria-label="Diagnosis note" />
          {changing && (
            <div>
              <p className="mb-1 text-xs" style={{ color: C.inkSoft }}>Revised work &amp; price (goes to the Admin{canApprove ? "" : " for approval"}):</p>
              <ManualLines lines={lines.length ? lines : [{ description: "", quantity: 1, unit_price: "" }]} onChange={setLines} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            {!changing ? (
              <>
                <button type="button" disabled={busy} onClick={() => submit(true)} className="flex items-center justify-center gap-1 py-2 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 600, opacity: busy ? 0.6 : 1 }}><Stethoscope size={13} /> Done — estimate is fine</button>
                <button type="button" disabled={busy} onClick={() => setChanging(true)} className="py-2 text-xs uppercase" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontWeight: 600 }}>Estimate needs to change</button>
              </>
            ) : (
              <>
                <button type="button" disabled={busy} onClick={() => submit(false)} className="py-2 text-xs uppercase" style={{ backgroundColor: C.blue, color: C.onAccent, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>{busy ? "Sending…" : canApprove ? "Apply revised estimate" : "Send to Admin"}</button>
                <button type="button" disabled={busy} onClick={() => setChanging(false)} className="py-2 text-xs uppercase" style={{ border: `1px solid ${C.rule}` }}>Back</button>
              </>
            )}
          </div>
        </div>
      )}
      <ApprovalLinkCard approval={approval} title="Revised estimate · send to the customer" onClose={() => setApproval(null)} />
      <div className="mt-2"><ErrorNote message={error} /></div>
    </section>
  );
}
