import { useMemo, useState } from "react";
import { AlertTriangle, Check, FilePen, Plus, Trash2, X } from "lucide-react";

import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import ApprovalLinkCard from "./ApprovalLinkCard";
import { revisionDiff } from "./performanceModel";
import { api } from "../../lib/api";
import { LINE_GRID, LineHeader } from "./ManualLines";
import { badCost, costField } from "./bookingModel";
import { C, F, money } from "../../lib/theme";

function startingLines(ticket) {
  const lines = ticket.current_estimate?.lines || [];
  return lines.map((l) => ({ service_id: l.service_id || null, description: l.description, quantity: l.quantity, unit_price: l.unit_price, unit_cost: l.unit_cost ?? "" }));
}

// Estimate changes after diagnosis: staff propose -> Admin/Super Admin accept (client re-approves) or decline -> back to staff.
export default function RevisionPanel({ ticket, services, canWork, canApprove, onChanged }) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState(() => startingLines(ticket));
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [approval, setApproval] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const pending = ticket.pending_revision;
  const estimate = ticket.current_estimate;
  const canPropose = canWork && !pending && estimate && ["Diagnosing", "In progress"].includes(ticket.status);
  const total = useMemo(() => lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0), [lines]);
  const past = (ticket.revisions || []).filter((r) => r.status !== "pending");

  const update = (i, f, v) => setLines((cur) => cur.map((l, n) => (n === i ? { ...l, [f]: v } : l)));
  const addService = (id) => {
    const s = services.find((x) => x.id === Number(id));
    if (s) setLines((cur) => [...cur, { service_id: s.id, description: s.label, quantity: 1, unit_price: s.charge }]);
  };

  const run = async (key, fn) => {
    setError(""); setBusy(key);
    try { await fn(); } catch (e) { setError(e.body?.detail || e.body?.reason?.[0] || e.body?.note?.[0] || e.message); } finally { setBusy(""); }
  };

  const propose = () => run("propose", async () => {
    if (!lines.length || lines.some((l) => !String(l.description || "").trim() || Number(l.quantity) < 1 || Number(l.unit_price) < 0 || badCost(l))) throw new Error("Add at least one valid line.");
    if (!reason.trim()) throw new Error("Say what changed and why.");
    const data = await api.post(`/tickets/${ticket.id}/revise/`, {
      reason: reason.trim(),
      lines: lines.map((l) => ({ service_id: l.service_id || null, description: l.description.trim(), quantity: Number(l.quantity), unit_price: Number(l.unit_price), ...costField(l) })),
    });
    setOpen(false); setReason("");
    if (data.approval) setApproval(data.approval);
    onChanged(data.ticket);
  });

  const decide = (decision) => run(decision, async () => {
    const data = await api.post(`/tickets/${ticket.id}/decide-revision/`, { decision, note: note.trim() });
    setNote("");
    if (data.approval) setApproval(data.approval);
    onChanged(data.ticket);
  });

  if (!pending && !ticket.on_hold_reason && !canPropose && !past.length && !approval) return null;

  return (
    <section className="mt-3 p-3" data-panel style={{ border: `1px solid ${ticket.on_hold_reason ? C.amber : C.rule}`, backgroundColor: ticket.on_hold_reason ? `${C.amber}0D` : C.slip2 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>Estimate revision</Eyebrow>
        {ticket.on_hold_reason && <Pill color={C.amber}>On hold</Pill>}
      </div>

      {ticket.on_hold_reason && (
        <p className="mt-2 flex items-start gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
          <AlertTriangle size={14} style={{ color: C.amber, flexShrink: 0 }} /> {ticket.on_hold_reason}. The job can't be finished until this is cleared.
        </p>
      )}

      {pending && (
        <div className="mt-2 space-y-1.5">
          <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            {pending.requested_by_name} proposes {money(pending.previous_total)} → <b style={{ color: C.ink }}>{money(pending.proposed_total)}</b>
            {" "}({revisionDiff(pending.previous_total, pending.proposed_total).diff > 0 ? "+" : ""}{money(revisionDiff(pending.previous_total, pending.proposed_total).diff)})
          </p>
          <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>Reason: {pending.reason}</p>
          {pending.lines.map((l, i) => <div key={i} className="flex justify-between text-xs" style={{ fontFamily: F.body, color: C.ink }}><span>{l.description} × {l.quantity}</span><span style={{ fontFamily: F.mono }}>{money(l.quantity * l.unit_price)}</span></div>)}
          {canApprove ? (
            <div className="border-t pt-2" style={{ borderColor: C.rule }}>
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="Note (required to decline)" className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }} />
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button type="button" onClick={() => decide("accept")} disabled={!!busy} className="flex items-center justify-center gap-1 py-2 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 600, opacity: busy ? 0.6 : 1 }}><Check size={13} /> Accept & send to client</button>
                <button type="button" onClick={() => decide("decline")} disabled={!!busy} className="flex items-center justify-center gap-1 py-2 text-xs uppercase" style={{ border: `1px solid ${C.carbon}`, color: C.carbon, fontWeight: 600, opacity: busy ? 0.6 : 1 }}><X size={13} /> Decline</button>
              </div>
            </div>
          ) : <p className="text-xs" style={{ color: C.amber }}>Waiting for the Admin / Super Admin to review.</p>}
        </div>
      )}

      <ApprovalLinkCard approval={approval} title="Revised estimate · send to the customer" onClose={() => setApproval(null)} />

      {canPropose && !open && (
        <button type="button" onClick={() => { setLines(startingLines(ticket)); setOpen(true); }} className="mt-3 flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontWeight: 600 }}>
          <FilePen size={13} /> {canApprove ? "Revise estimate" : "Propose revised estimate"}
        </button>
      )}

      {open && (
        <div className="mt-3 space-y-2">
          <LineHeader small />
          {lines.map((l, i) => (
            <div key={i} style={LINE_GRID}>
              <input className="min-w-0 px-2 py-1 text-xs" value={l.description} onChange={(e) => update(i, "description", e.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Work description" />
              <input className="min-w-0 px-2 py-1 text-xs" type="number" min="1" value={l.quantity} onChange={(e) => update(i, "quantity", e.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Quantity" />
              <input className="min-w-0 px-2 py-1 text-xs" type="number" min="0" value={l.unit_price} onChange={(e) => update(i, "unit_price", e.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Unit price" />
              <input className="min-w-0 px-2 py-1 text-xs" type="number" min="0" value={l.unit_cost ?? ""} onChange={(e) => update(i, "unit_cost", e.target.value)} placeholder="₹ cost" style={{ border: `1px dashed ${C.rule}` }} aria-label="Our cost (staff only)" />
              <button type="button" onClick={() => setLines((cur) => cur.filter((_, n) => n !== i))} className="flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button>
            </div>
          ))}
          <select defaultValue="" onChange={(e) => { addService(e.target.value); e.target.value = ""; }} className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }}>
            <option value="">Add a catalogue service…</option>
            {services.map((s) => <option key={s.id} value={s.id}>{s.label} — {money(s.charge)}</option>)}
          </select>
          <button type="button" onClick={() => setLines((cur) => [...cur, { service_id: null, description: "", quantity: 1, unit_price: 0 }])} className="flex items-center gap-1 text-xs" style={{ color: C.blue }}><Plus size={13} /> Add custom line</button>
          <p className="text-right text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Was {money(estimate?.total_amount)} · now <b style={{ color: C.ink }}>{money(total)}</b></p>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={1000} placeholder="What did you find, and why does the estimate change?" className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }} aria-label="Reason for revision" />
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={propose} disabled={!!busy} className="py-2 text-xs uppercase" style={{ backgroundColor: C.blue, color: C.onAccent, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>{busy === "propose" ? "Sending…" : canApprove ? "Apply revision" : "Send to Admin"}</button>
            <button type="button" onClick={() => setOpen(false)} className="py-2 text-xs uppercase" style={{ border: `1px solid ${C.rule}` }}>Cancel</button>
          </div>
        </div>
      )}

      {past.length > 0 && (
        <div className="mt-3 border-t pt-2" style={{ borderColor: C.rule }}>
          {past.map((r) => (
            <p key={r.id} className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
              {money(r.previous_total)} → {money(r.proposed_total)} · {r.status}{r.decided_by_name ? ` by ${r.decided_by_name}` : ""}{r.decision_note ? ` — ${r.decision_note}` : ""}
            </p>
          ))}
        </div>
      )}
      <div className="mt-2"><ErrorNote message={error} /></div>
    </section>
  );
}
