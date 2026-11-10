import { useEffect, useState } from "react";
import { BadgeCheck, CheckCircle2, Copy, FileText, HandCoins, Link2, MapPin, MessageCircle, Navigation, Pencil, Phone, PlayCircle, Send, Stethoscope, UserCheck, Wrench, XCircle } from "lucide-react";
import { api } from "../../lib/api";
import { copyText } from "../../lib/copyText";
import { C, F, fmt, money, todayISO } from "../../lib/theme";
import { ErrorNote, Pill } from "../Atoms";
import BillEditor from "./BillEditor";
import PartsPanel, { IssuePartsModal } from "./PartsPanel";
import LeadFormModal from "./LeadFormModal";
import Prompt, { Modal, inputStyle } from "./Prompt";
import { PAY_METHODS, PRIORITY, mapsLink, statusOf, telLink, validatePayment } from "./leadModel";

const dt = (v) => (v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

function Btn({ icon: Icon, children, onClick, primary, danger, disabled }) {
  const color = danger ? C.carbon : C.orange;
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="flex min-h-[44px] items-center justify-center gap-1.5 px-4 py-2 text-xs disabled:opacity-50"
      style={{ fontFamily: F.body, fontWeight: 700, backgroundColor: primary ? color : "transparent", color: primary ? C.onAccent : danger ? C.carbon : C.ink, border: primary ? "none" : `1px solid ${danger ? C.carbon : C.rule}` }}>
      {Icon && <Icon size={14} />}{children}
    </button>
  );
}

function PaymentModal({ lead, invoice, onClose, onDone }) {
  const [form, setForm] = useState({ pay_method: "Cash", payment_reference: "", paid_on: todayISO() });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => { setForm((f) => ({ ...f, [k]: e.target.value })); setError(""); };
  const submit = async (e) => {
    e.preventDefault();
    const problem = validatePayment(form, todayISO());
    if (problem) return setError(problem);
    setBusy(true);
    try {
      onDone(await api.post(`/leads/${lead.id}/collect/`, { ...form, invoice: invoice.id }));
    } catch (err) {
      setError(err.body?.detail || [].concat(...Object.values(err.body || {})).join(" ") || err.message);
      setBusy(false);
    }
  };
  return (
    <Modal title={`${invoice.is_advance ? "Collect advance" : "Collect"} ${money(invoice.total)} · ${invoice.code}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        <label className="block">Paid by
          <select value={form.pay_method} onChange={set("pay_method")} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>{PAY_METHODS.map((m) => <option key={m}>{m}</option>)}</select>
        </label>
        {form.pay_method !== "Cash" && <label className="block">Reference (UPI / UTR / cheque no.) *
          <input value={form.payment_reference} onChange={set("payment_reference")} maxLength={80} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
        </label>}
        <label className="block">Paid on
          <input type="date" value={form.paid_on} max={todayISO()} onChange={set("paid_on")} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
        </label>
        <ErrorNote message={error} />
        <button disabled={busy} className="flex min-h-[44px] w-full items-center justify-center py-2.5 uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 700, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>{busy ? "Saving…" : invoice.is_advance ? "Record advance payment" : "Record payment & check out"}</button>
      </form>
    </Modal>
  );
}

function LinkPanel({ info, lead, onClose }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-4 p-4" style={{ border: `1px solid ${C.green}`, backgroundColor: `${C.green}0d` }}>
      <p className="text-sm" style={{ fontWeight: 700 }}>Approval link ready — valid for 24 hours</p>
      <p className="mt-1 break-all text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{info.approval_url}</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Btn icon={Copy} onClick={async () => { await copyText(info.approval_url); setCopied(true); }}>{copied ? "Copied" : "Copy link"}</Btn>
        <a href={info.whatsapp_url} target="_blank" rel="noreferrer" className="flex min-h-[44px] items-center justify-center gap-1.5 px-4 py-2 text-xs" style={{ border: `1px solid ${C.rule}`, fontWeight: 700 }}><MessageCircle size={14} /> Chat on WhatsApp</a>
        <Btn onClick={onClose}>Done</Btn>
      </div>
      {info.delivery && <p className="mt-2 text-xs" style={{ color: C.inkSoft }}>WhatsApp delivery: {info.delivery}</p>}
    </div>
  );
}

export default function LeadDetail({ lead, stockPoints, onChange, onClose }) {
  const [dialog, setDialog] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [link, setLink] = useState(null);
  const has = (a) => lead.actions.includes(a);
  const st = statusOf(lead.status);
  const tone = (t) => C[t] || C.inkSoft;

  const run = async (path, body = {}, after) => {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/leads/${lead.id}/${path}/`, body);
      if (after) after(res);
      else onChange(res);
      setDialog(null);
      return res;
    } catch (e) {
      const b = e.body || {};
      const msg = b.detail || [].concat(...Object.values(b).map((v) => [].concat(v))).join(" ") || e.message;
      setError(msg);
      throw new Error(msg);
    } finally {
      setBusy(false);
    }
  };
  const safe = (fn) => async () => { try { await fn(); } catch { /* shown in the error note */ } };

  const checkIn = () => {
    const go = (lat, lng) => run("check_in", { lat, lng }).catch(() => {});
    if (!navigator.geolocation) return go(null, null);
    navigator.geolocation.getCurrentPosition((p) => go(p.coords.latitude, p.coords.longitude), () => go(null, null), { timeout: 6000 });
  };

  const outstanding = lead.invoices.filter((i) => i.status !== "Paid" && i.status !== "Cancelled" && i.status !== "Refunded");
  const bill = lead.invoices.filter((i) => !i.is_advance && i.status !== "Cancelled").slice(-1)[0];

  return (
    <div className="fixed inset-0 z-30 flex justify-end" style={{ backgroundColor: "rgba(4,9,18,0.55)" }} onClick={onClose}>
      <aside role="dialog" aria-label={`Job ${lead.code}`} className="h-full w-full max-w-xl overflow-y-auto p-5 sm:p-6" style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{lead.code} · {lead.stock_point_name}</p>
            <h2 className="mt-1 break-words text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{lead.party_name}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2"><Pill color={tone(st.tone)}>{st.label}</Pill>{lead.priority !== "normal" && <Pill color={lead.priority === "urgent" ? C.carbon : C.inkSoft}>{PRIORITY[lead.priority]}</Pill>}</div>
          </div>
          <button onClick={onClose} aria-label="Close job" className="px-2 text-xl" style={{ color: C.inkSoft }}>×</button>
        </div>

        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex gap-2"><MapPin size={15} className="mt-0.5 shrink-0" style={{ color: C.inkSoft }} /><div className="min-w-0"><span className="break-words">{lead.site_address}</span><a href={mapsLink(lead)} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-1 text-xs" style={{ color: C.orange, fontWeight: 700 }}><Navigation size={12} />Directions</a></div></div>
          {(lead.contact_phone || lead.party_phone) && <div className="flex gap-2"><Phone size={15} className="mt-0.5 shrink-0" style={{ color: C.inkSoft }} /><a href={telLink(lead.contact_phone || lead.party_phone)} style={{ color: C.orange, fontWeight: 700 }}>{lead.contact_name ? `${lead.contact_name} · ` : ""}{lead.contact_phone || lead.party_phone}</a></div>}
          {lead.device && <div className="flex gap-2"><Wrench size={15} className="mt-0.5 shrink-0" style={{ color: C.inkSoft }} /><span>{lead.device}</span></div>}
          <div className="flex gap-2"><UserCheck size={15} className="mt-0.5 shrink-0" style={{ color: C.inkSoft }} /><span>{lead.assigned_to_name || "Not assigned yet"}{lead.preferred_at && ` · visit ${dt(lead.preferred_at)}`}</span></div>
        </dl>
        <p className="mt-3 whitespace-pre-line break-words p-3 text-sm" style={{ backgroundColor: C.slip2 }}><span className="block text-xs" style={{ color: C.inkSoft }}>Problem reported</span>{lead.issue}</p>
        {lead.diagnosis && <p className="mt-2 whitespace-pre-line break-words p-3 text-sm" style={{ backgroundColor: C.slip2 }}><span className="block text-xs" style={{ color: C.inkSoft }}>Diagnosis</span>{lead.diagnosis}</p>}
        {lead.reject_reason && <p className="mt-2 break-words p-3 text-sm" style={{ backgroundColor: `${C.carbon}10` }}><span className="block text-xs" style={{ color: C.carbon }}>Client declined</span>{lead.reject_reason}</p>}
        {lead.repair_ticket_code && <p className="mt-2 break-words p-3 text-sm" style={{ backgroundColor: `${C.stamp}12` }}><span className="block text-xs" style={{ color: C.stamp }}>Taken to the store</span>Now repair ticket <strong style={{ fontFamily: F.mono }}>{lead.repair_ticket_code}</strong> in Repairs & Service — the in-house team takes it from here.</p>}
        {lead.cancel_reason && <p className="mt-2 break-words p-3 text-sm" style={{ backgroundColor: C.slip2 }}><span className="block text-xs" style={{ color: C.inkSoft }}>Cancelled</span>{lead.cancel_reason}</p>}

        {lead.quote && (
          <section className="mt-4" aria-label="Bill">
            <div className="flex items-center justify-between"><p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Bill v{lead.quote.version}</p><Pill color={lead.quote.status === "approved" ? C.green : lead.quote.status === "rejected" ? C.carbon : C.amber}>{lead.quote.status}</Pill></div>
            {lead.quote.lines.map((l) => (
              <div key={l.id} className="mt-1 flex justify-between gap-3 px-3 py-2 text-sm" style={{ backgroundColor: C.slip2 }}>
                <span className="min-w-0 break-words">{l.description}{l.qty > 1 && <span style={{ color: C.inkSoft }}> × {l.qty}</span>}</span><span style={{ fontFamily: F.mono }}>{money(l.amount)}</span>
              </div>
            ))}
            <div className="mt-1 flex justify-between px-3 py-2" style={{ border: `1px solid ${C.rule}` }}><strong className="text-sm">Total</strong><strong style={{ fontFamily: F.mono }}>{money(lead.quote.total)}</strong></div>
            {lead.advance_received > 0 && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Advance received {money(lead.advance_received)} — deducted on the final invoice.</p>}
            {lead.quote.on_behalf && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Prepared by {lead.quote.prepared_by_name} on the technician's behalf.</p>}
          </section>
        )}

        <PartsPanel lead={lead} onIssue={() => setDialog("issue_parts")} onReturn={(p) => setDialog({ ret: p })} onWriteOff={(p) => setDialog({ off: p })} />

        {lead.invoices.length > 0 && (
          <section className="mt-4" aria-label="Invoices">
            <p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Invoices</p>
            {lead.invoices.map((i) => (
              <div key={i.id} className="mt-1 flex items-center justify-between gap-3 px-3 py-2 text-sm" style={{ backgroundColor: C.slip2 }}>
                <span><span style={{ fontFamily: F.mono }}>{i.code}</span>{i.is_advance && <span className="ml-2 text-xs" style={{ color: C.inkSoft }}>advance</span>}</span>
                <span className="flex items-center gap-2"><span style={{ fontFamily: F.mono }}>{money(i.total)}</span><Pill color={i.status === "Paid" ? C.green : i.status === "Cancelled" ? C.inkSoft : C.amber}>{i.status === "Payment link sent" ? "Unpaid" : i.status}</Pill></span>
              </div>
            ))}
          </section>
        )}

        {link && <LinkPanel info={link} lead={lead} onClose={() => setLink(null)} />}
        <ErrorNote message={error} />

        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          {has("check_in") && <Btn primary icon={Navigation} disabled={busy} onClick={checkIn}>I've reached the site</Btn>}
          {has("diagnose") && <Btn primary={lead.status === "visiting"} icon={Stethoscope} onClick={() => setDialog("diagnose")}>{lead.diagnosis ? "Update diagnosis" : "Record diagnosis"}</Btn>}
          {has("quote") && <Btn primary={lead.status === "diagnosed" && !lead.quote} icon={FileText} onClick={() => setDialog("quote")}>{lead.quote ? "Revise bill" : "Prepare bill"}</Btn>}
          {has("send_link") && <Btn primary={lead.status === "diagnosed" && !!lead.quote} icon={Link2} disabled={busy} onClick={safe(() => run("send_link", {}, (res) => { setLink(res); onChange(res.lead); }))}>{lead.status === "awaiting_approval" ? "Send a fresh approval link" : "Create approval link"}</Btn>}
          {has("approve") && <Btn icon={BadgeCheck} onClick={() => setDialog("approve")}>Approve on client's behalf</Btn>}
          {has("start") && <Btn primary icon={PlayCircle} disabled={busy} onClick={safe(() => run("start"))}>Start work</Btn>}
          {has("complete") && <Btn primary icon={CheckCircle2} onClick={() => setDialog("complete")}>Work done · raise invoice</Btn>}
          {has("collect") && bill && bill.status !== "Paid" && <Btn primary icon={HandCoins} onClick={() => setDialog({ pay: bill })}>Collect {money(bill.total)} & check out</Btn>}
          {has("collect_advance") && outstanding.filter((i) => i.is_advance).map((i) => <Btn key={i.id} icon={HandCoins} onClick={() => setDialog({ pay: i })}>Collect advance {money(i.total)}</Btn>)}
          {has("advance") && <Btn icon={HandCoins} onClick={() => setDialog("advance")}>Ask for advance</Btn>}
          {has("assign") && <Btn icon={UserCheck} onClick={() => setDialog("assign")}>{lead.assigned_to ? "Reassign" : "Assign technician"}</Btn>}
          {has("edit") && <Btn icon={Pencil} onClick={() => setDialog("edit")}>Edit details</Btn>}
          {has("reschedule") && <Btn icon={Send} onClick={() => setDialog("reschedule")}>Reschedule</Btn>}
          {has("close_credit") && <Btn icon={XCircle} onClick={() => setDialog("credit")}>Check out, payment pending</Btn>}
          {has("to_store") && <Btn icon={Wrench} onClick={() => setDialog("to_store")}>Can't fix on site · take to store</Btn>}
          {has("cancel") && <Btn danger icon={XCircle} onClick={() => setDialog("cancel")}>Cancel job</Btn>}
        </div>

        <section className="mt-6" aria-label="Timeline">
          <p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Timeline</p>
          <ol className="mt-2 space-y-2 border-l pl-4" style={{ borderColor: C.rule }}>
            {[...lead.events].reverse().map((ev) => (
              <li key={ev.id} className="text-sm"><span className="block break-words">{ev.text || ev.event}</span><span className="text-xs" style={{ color: C.inkSoft }}>{dt(ev.created_at)}{ev.actor_name && ` · ${ev.actor_name}`}</span></li>
            ))}
          </ol>
        </section>
      </aside>

      {dialog === "edit" && <LeadFormModal lead={lead} stockPoints={stockPoints} onClose={() => setDialog(null)} onSaved={(l) => { onChange(l); setDialog(null); }} />}
      {dialog === "quote" && <BillEditor lead={lead} onClose={() => setDialog(null)} onSaved={(l) => { onChange(l); setDialog(null); }} />}
      {dialog?.pay && <PaymentModal lead={lead} invoice={dialog.pay} onClose={() => setDialog(null)} onDone={(l) => { onChange(l); setDialog(null); }} />}
      {dialog === "diagnose" && <Prompt title="Diagnosis" intro="Write what you found on site — the client sees this with the bill." fields={[{ name: "diagnosis", label: "Findings", type: "textarea", required: true, maxLength: 4000, dictate: true, placeholder: "Type, or tap Speak and say what you found" }]} initial={{ diagnosis: lead.diagnosis }} submitLabel="Save diagnosis" onClose={() => setDialog(null)} onSubmit={(v) => run("diagnose", v)} />}
      {dialog === "approve" && <Prompt title="Approve on client's behalf" tone={C.green} intro="Use this only when the client has agreed by phone or in person. The reason is stored with the approval." fields={[{ name: "reason", label: "Reason / how the client agreed", type: "textarea", required: true, maxLength: 500 }]} submitLabel="Record approval" onClose={() => setDialog(null)} onSubmit={(v) => run("approve", v)} />}
      {dialog === "complete" && <Prompt title="Work done" intro="Parts and products on the bill are counted against what the technician carries first, then taken off this store's shelf, and the final invoice is raised." fields={[{ name: "notes", label: "Work notes (optional)", type: "textarea", maxLength: 2000 }]} submitLabel="Complete & raise invoice" onClose={() => setDialog(null)} onSubmit={(v) => run("complete", v)} />}
      {dialog === "advance" && <Prompt title="Ask for an advance" intro="Raises an advance invoice. It is optional, and is deducted from the final bill once paid." fields={[{ name: "amount", label: "Amount (₹)", required: true, inputMode: "numeric" }]} initial={{ amount: lead.advance_amount || "" }} submitLabel="Raise advance invoice" onClose={() => setDialog(null)} onSubmit={(v) => run("advance", v)} />}
      {dialog === "reschedule" && <Prompt title="Reschedule visit" fields={[{ name: "preferred_at", label: "New date & time", type: "datetime-local", required: true }, { name: "reason", label: "Reason (optional)" }]} submitLabel="Reschedule" onClose={() => setDialog(null)} onSubmit={(v) => run("reschedule", { ...v, preferred_at: new Date(v.preferred_at).toISOString() })} />}
      {dialog === "credit" && <Prompt title="Check out with payment pending" tone={C.carbon} intro="The invoice stays unpaid in Sales & Invoices. Only an Admin can do this." fields={[{ name: "reason", label: "Reason", required: true }]} submitLabel="Check out" onClose={() => setDialog(null)} onSubmit={(v) => run("close_credit", v)} />}
      {dialog === "cancel" && <Prompt title="Cancel job" tone={C.carbon} fields={[{ name: "reason", label: "Reason", required: true }, ...(lead.checked_in_at && lead.visit_charge ? [{ name: "charge_visit", label: `Bill the visit charge (${money(lead.visit_charge)})`, type: "checkbox" }] : [])]} submitLabel="Cancel job" onClose={() => setDialog(null)} onSubmit={(v) => run("cancel", v)} />}
      {dialog === "to_store" && <Prompt title="Take to the store for repair" intro="A repair ticket is opened at this store for the in-house technician / repair staff. Any advance already paid goes across to the ticket." fields={[{ name: "reason", label: "Why it can't be fixed on site", type: "textarea", required: true, maxLength: 300 }, ...(lead.visit_charge ? [{ name: "charge_visit", label: `Bill the visit charge (${money(lead.visit_charge)}) now`, type: "checkbox" }] : [])]} initial={{ charge_visit: true }} submitLabel="Open repair ticket" onClose={() => setDialog(null)} onSubmit={(v) => run("to_store", { reason: v.reason, charge_visit: lead.visit_charge ? !!v.charge_visit : false })} />}
      {dialog === "issue_parts" && <IssuePartsModal lead={lead} onClose={() => setDialog(null)} onSubmit={(v) => run("issue_parts", v)} />}
      {dialog?.ret && <Prompt title={`Take back — ${dialog.ret.description}`} intro={`${dialog.ret.technician_name} is holding ${dialog.ret.outstanding}. What you take back goes onto ${lead.stock_point_name}'s shelf.`} fields={[{ name: "qty", label: "Quantity handed back", required: true, inputMode: "numeric" }]} initial={{ qty: String(dialog.ret.outstanding) }} submitLabel="Add back to stock" onClose={() => setDialog(null)} onSubmit={(v) => run("return_parts", { issue: dialog.ret.id, qty: Number(v.qty) })} />}
      {dialog?.off && <Prompt title={`Lost / damaged — ${dialog.off.description}`} tone={C.carbon} intro={`Closes the stock out of ${dialog.off.technician_name}'s account. It is NOT added back to the shelf, so this is a loss. The reason is kept in the job timeline.`} fields={[{ name: "qty", label: "Quantity lost or damaged", required: true, inputMode: "numeric" }, { name: "reason", label: "What happened", required: true }]} initial={{ qty: String(dialog.off.outstanding) }} submitLabel="Write off" onClose={() => setDialog(null)} onSubmit={(v) => run("write_off_parts", { issue: dialog.off.id, qty: Number(v.qty), reason: v.reason })} />}
      {dialog === "assign" && <AssignDialog lead={lead} onClose={() => setDialog(null)} onDone={(l) => { onChange(l); setDialog(null); }} />}
    </div>
  );
}

function AssignDialog({ lead, onClose, onDone }) {
  const [techs, setTechs] = useState(null);
  useEffect(() => { api.get(`/leads/technicians/?stock_point=${lead.stock_point}`).then(setTechs).catch(() => setTechs([])); }, [lead.stock_point]);
  if (!techs) return <Modal title="Assign technician" onClose={onClose}><p className="text-sm" style={{ color: C.inkSoft }}>Loading…</p></Modal>;
  return (
    <Prompt title="Assign technician" fields={[{ name: "assigned_to", label: "Technician", type: "select", required: true, options: [{ value: "", label: techs.length ? "Select…" : "No technicians found — give a role the leads.work permission" }, ...techs.map((t) => ({ value: t.id, label: t.kind === "outsourced" ? `${t.name} — Outsourced · ${t.company}` : t.kind === "field" ? `${t.name} — Field technician` : t.name }))] }]}
      initial={{ assigned_to: lead.assigned_to || "" }} submitLabel="Assign & notify" onClose={onClose} onSubmit={async (v) => onDone(await api.post(`/leads/${lead.id}/assign/`, v))} />
  );
}
