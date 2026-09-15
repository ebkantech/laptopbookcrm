import { useMemo, useState } from "react";
import { CheckCircle2, Copy, ExternalLink, FileCheck2, Plus, Send, ShieldCheck, Trash2 } from "lucide-react";

import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import { api } from "../../lib/api";
import { C, F, money } from "../../lib/theme";


const DEFAULT_TERMS = "I approve the final repair work and total amount shown in this estimate. Any later change will be coordinated separately with the service centre.";

function initialLines(ticket) {
  const existing = ticket.current_estimate?.lines;
  if (existing?.length) return existing.map((line) => ({ service_id: line.service_id || null, description: line.description, quantity: line.quantity, unit_price: line.unit_price }));
  return (ticket.services || []).map((service) => ({ service_id: service.id, description: service.label, quantity: 1, unit_price: service.charge }));
}

function statusLabel(status) {
  return {
    not_sent: "Estimate not sent", pending: "Customer decision pending", expired: "Link expired", revoked: "Link revoked",
    rejected: "Customer rejected", customer_approved: "Customer approved", admin_approved: "Admin approved", superadmin_approved: "Super Admin approved",
  }[status] || status;
}

export default function EstimateApprovalPanel({ ticket, services, canManage, canApprove, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [lines, setLines] = useState(() => initialLines(ticket));
  const [terms, setTerms] = useState(ticket.current_estimate?.terms || DEFAULT_TERMS);
  const [reason, setReason] = useState("");
  const [links, setLinks] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const estimate = ticket.current_estimate;
  const status = ticket.approval_status || "not_sent";
  const approved = ["customer_approved", "admin_approved", "superadmin_approved"].includes(status);
  const total = useMemo(() => lines.reduce((sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unit_price) || 0), 0), [lines]);

  const updateLine = (index, field, value) => setLines((current) => current.map((line, i) => i === index ? { ...line, [field]: value } : line));
  const removeLine = (index) => setLines((current) => current.filter((_, i) => i !== index));
  const addService = (id) => {
    const service = services.find((item) => item.id === Number(id));
    if (service) setLines((current) => [...current, { service_id: service.id, description: service.label, quantity: 1, unit_price: service.charge }]);
  };

  const finalize = async () => {
    setError("");
    if (!lines.length || lines.some((line) => !String(line.description || "").trim() || Number(line.quantity) < 1 || Number(line.unit_price) < 0)) {
      setError("Add at least one valid work or cost line.");
      return;
    }
    setBusy("finalize");
    try {
      const updated = await api.post(`/tickets/${ticket.id}/finalize-estimate/`, {
        lines: lines.map((line) => ({ service_id: line.service_id || null, description: line.description.trim(), quantity: Number(line.quantity), unit_price: Number(line.unit_price) })),
        terms: terms.trim(),
      });
      onChanged(updated);
    } catch (requestError) { setError(requestError.body?.detail || requestError.message); }
    finally { setBusy(""); }
  };

  const generateLink = async () => {
    setError(""); setBusy("link");
    try {
      const data = await api.post(`/tickets/${ticket.id}/approval-link/`);
      setLinks(data);
      onChanged(data.ticket);
    } catch (requestError) { setError(requestError.body?.detail || requestError.message); }
    finally { setBusy(""); }
  };

  const approveOnBehalf = async () => {
    setError("");
    if (!reason.trim()) { setError("Enter the reason for approving on behalf of the customer."); return; }
    setBusy("approve");
    try { onChanged(await api.post(`/tickets/${ticket.id}/approve-on-behalf/`, { reason: reason.trim() })); }
    catch (requestError) { setError(requestError.body?.detail || requestError.message); }
    finally { setBusy(""); }
  };

  const copy = async (value) => {
    try { await navigator.clipboard.writeText(value); } catch { setError("Copy the link manually from the box below."); }
  };

  return (
    <section className="mt-5 p-3" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><Eyebrow>Customer approval</Eyebrow><p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Final work and cost must be approved before original repair work starts.</p></div>
        <Pill color={approved ? C.green : status === "pending" ? C.amber : C.inkSoft}>{statusLabel(status)}</Pill>
      </div>

      {estimate && !editing && (
        <div className="mt-3 space-y-1.5">
          {estimate.lines.map((line) => <div key={line.id} className="flex items-center justify-between text-xs" style={{ fontFamily: F.body, color: C.ink }}><span>{line.description} × {line.quantity}</span><span style={{ fontFamily: F.mono }}>{money(line.line_total)}</span></div>)}
          <div className="flex items-center justify-between border-t pt-2 text-sm" style={{ borderColor: C.rule, fontFamily: F.mono, fontWeight: 700 }}><span>Final estimate</span><span>{money(estimate.total_amount)}</span></div>
        </div>
      )}

      {canManage && !approved && ticket.status === "Diagnosing" && (
        <button onClick={() => setEditing((value) => !value)} className="mt-3 flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600 }}>
          <FileCheck2 size={13} /> {editing ? "Close estimate editor" : estimate ? "Revise final estimate" : "Prepare final estimate"}
        </button>
      )}

      {editing && (
        <div className="mt-3 space-y-2">
          {lines.map((line, index) => <div key={`${line.service_id || "custom"}-${index}`} className="grid grid-cols-12 gap-1.5"><input className="col-span-6 px-2 py-1 text-xs" value={line.description} onChange={(event) => updateLine(index, "description", event.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Work description" /><input className="col-span-2 px-2 py-1 text-xs" type="number" min="1" value={line.quantity} onChange={(event) => updateLine(index, "quantity", event.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Quantity" /><input className="col-span-3 px-2 py-1 text-xs" type="number" min="0" value={line.unit_price} onChange={(event) => updateLine(index, "unit_price", event.target.value)} style={{ border: `1px solid ${C.rule}` }} aria-label="Unit price" /><button onClick={() => removeLine(index)} className="col-span-1 flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button></div>)}
          <select defaultValue="" onChange={(event) => { addService(event.target.value); event.target.value = ""; }} className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }}><option value="">Add a catalogue service…</option>{services.map((service) => <option key={service.id} value={service.id}>{service.label} — {money(service.charge)}</option>)}</select>
          <button onClick={() => setLines((current) => [...current, { service_id: null, description: "", quantity: 1, unit_price: 0 }])} className="flex items-center gap-1 text-xs" style={{ color: C.blue }}><Plus size={13} /> Add custom line</button>
          <p className="text-right text-sm" style={{ fontFamily: F.mono, fontWeight: 700 }}>Total: {money(total)}</p>
          <textarea value={terms} onChange={(event) => setTerms(event.target.value)} rows={3} maxLength={2000} className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }} aria-label="Approval terms" />
          <button onClick={finalize} disabled={busy === "finalize"} className="flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ backgroundColor: C.blue, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy === "finalize" ? 0.6 : 1 }}><FileCheck2 size={13} /> {busy === "finalize" ? "Saving…" : "Freeze final estimate"}</button>
        </div>
      )}

      {estimate && !approved && canManage && !editing && <button onClick={generateLink} disabled={busy === "link"} className="mt-3 flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy === "link" ? 0.6 : 1 }}><Send size={13} /> {busy === "link" ? "Generating…" : "Generate 24-hour approval link"}</button>}

      {links && <div className="mt-3 space-y-2"><input readOnly value={links.approval_url} className="w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }} /><div className="grid grid-cols-2 gap-2"><button onClick={() => copy(links.approval_url)} className="flex items-center justify-center gap-1 py-2 text-xs" style={{ border: `1px solid ${C.rule}` }}><Copy size={13} /> Copy link</button><a href={links.whatsapp_url} target="_blank" rel="noreferrer" className="flex items-center justify-center gap-1 py-2 text-xs" style={{ backgroundColor: C.green, color: C.onAccent }}><ExternalLink size={13} /> Open WhatsApp</a></div></div>}

      {estimate && !approved && canApprove && !editing && <div className="mt-3 border-t pt-3" style={{ borderColor: C.rule }}><label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Admin/Super Admin approval reason</label><textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} maxLength={500} className="mt-1 w-full px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }} /><button onClick={approveOnBehalf} disabled={busy === "approve"} className="mt-2 flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ backgroundColor: C.blue, color: C.onAccent, fontFamily: F.body, fontWeight: 600 }}><ShieldCheck size={13} /> {busy === "approve" ? "Recording…" : "Approve on behalf"}</button></div>}
      {approved && <p className="mt-3 flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.green }}><CheckCircle2 size={14} /> Approved estimate snapshot is locked for this workflow.</p>}
      <div className="mt-3"><ErrorNote message={error} /></div>
    </section>
  );
}
