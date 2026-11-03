import { useState } from "react";
import { BellRing, CheckCircle2, ClipboardCheck, Phone, XCircle } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { Pill } from "../Atoms";
import Prompt from "../leads/Prompt";

const CLAIM_COLOR = { open: C.amber, approved: C.blue, rejected: C.carbon, resolved: C.green };
const smallBtn = (color = C.ink) => ({ fontFamily: F.body, fontWeight: 700, color, border: `1px solid ${color === C.ink ? C.rule : color}` });
const msg = (e) => e.body?.detail || [].concat(...Object.values(e.body || {}).map((v) => [].concat(v))).join(" ") || e.message;

export function SummaryStrip({ summary }) {
  if (!summary) return null;
  const tiles = [
    ["Active", summary.active, C.green],
    ["Expiring in 30 days", summary.expiring, summary.expiring ? C.amber : C.inkSoft],
    ["Expired", summary.expired, C.inkSoft],
    ["Open claims", summary.open_claims, summary.open_claims ? C.blue : C.inkSoft],
    ["Claim cost this month", money(summary.claim_cost_this_month), C.ink],
  ];
  return (
    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" aria-label="Warranty summary">
      {tiles.map(([label, value, color]) => (
        <div key={label} data-panel className="px-3 py-2.5" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          <p className="text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>{label}</p>
          <p className="mt-0.5 text-lg" style={{ fontFamily: F.display, fontWeight: 700, color }}>{value}</p>
        </div>
      ))}
    </div>
  );
}

export function ExpiringList({ items, canManage, onRemind, onRemindAll }) {
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Customers whose cover ends in the next 30 days — call them, or send the reminder.</p>
        {canManage && <button type="button" onClick={onRemindAll} className="flex min-h-[36px] items-center gap-1.5 px-3 text-xs" style={smallBtn(C.orange)}><BellRing size={13} />Send all due reminders</button>}
      </div>
      <div className="mt-2 space-y-2">
        {items.map((w) => (
          <div key={w.id} data-panel className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ border: `1px solid ${w.days_left <= 7 ? C.carbon : C.rule}`, backgroundColor: C.slip }}>
            <div className="min-w-[170px] flex-1">
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600 }}>{w.party_name}</p>
              <a href={`tel:${w.party_phone}`} className="inline-flex items-center gap-1 text-xs" style={{ fontFamily: F.mono, color: C.orange }}><Phone size={11} />{w.party_phone}</a>
            </div>
            <div className="min-w-[180px] flex-1"><p className="text-sm" style={{ fontFamily: F.body }}>{w.item_label}</p><p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>ends {fmt(w.end_date)}</p></div>
            <Pill color={w.days_left <= 7 ? C.carbon : C.amber}>{w.days_left <= 0 ? "ends today" : `${w.days_left} day${w.days_left === 1 ? "" : "s"} left`}</Pill>
            {w.reminded && <Pill color={C.green}>reminded</Pill>}
            {canManage && <button type="button" onClick={() => onRemind(w)} className="flex min-h-[36px] items-center gap-1.5 px-3 text-xs" style={smallBtn()}><BellRing size={13} />{w.reminded ? "Remind again" : "Send reminder"}</button>}
          </div>
        ))}
        {!items.length && <p className="px-4 py-10 text-center text-sm" style={{ border: `1px dashed ${C.ruleStrong}`, color: C.inkSoft }}>Nothing expires in the next 30 days.</p>}
      </div>
    </div>
  );
}

export function RaiseClaimPrompt({ warranty, onClose, onDone }) {
  return (
    <Prompt title={`Warranty claim — ${warranty.item_label}`} intro={`${warranty.party_name} · cover ends ${fmt(warranty.end_date)}. The customer is messaged that the claim is logged.`}
      fields={[{ name: "issue", label: "What is wrong?", type: "textarea", required: true, maxLength: 2000 }, { name: "repair_code", label: "Repair job code (optional, e.g. RPR-1050)" }]}
      submitLabel="Log claim" onClose={onClose}
      onSubmit={async (v) => { try { onDone(await api.post("/warranty-claims/", { warranty: warranty.id, ...v })); } catch (e) { throw new Error(msg(e)); } }} />
  );
}

export function ClaimsList({ claims, canManage, onChanged }) {
  const [dialog, setDialog] = useState(null); // { kind: "reject"|"resolve", claim }
  const call = async (path, body) => { try { onChanged(await api.post(path, body)); } catch (e) { throw new Error(msg(e)); } };
  return (
    <div className="mt-3 space-y-2">
      {claims.map((c) => (
        <div key={c.id} data-panel className="px-4 py-3" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{c.code} · {fmt(c.created_at)}</p>
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600 }}>{c.party_name} — {c.warranty_label}</p>
            </div>
            <div className="flex items-center gap-2"><Pill color={CLAIM_COLOR[c.status]}>{c.status_label}</Pill>{c.status === "resolved" && <Pill color={C.ink}>cost {money(c.cost)}</Pill>}</div>
          </div>
          <p className="mt-1 break-words text-sm">{c.issue}</p>
          {c.decision_note && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>{c.status === "rejected" ? "Rejected: " : "Note: "}{c.decision_note}</p>}
          {c.status === "resolved" && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>{c.resolution}{c.resolution_note && ` — ${c.resolution_note}`}{c.repair_code && ` · job ${c.repair_code}`}</p>}
          {canManage && c.status === "open" && (
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" onClick={() => call(`/warranty-claims/${c.id}/decide/`, { decision: "approve" }).catch(() => {})} className="flex min-h-[36px] items-center gap-1.5 px-3 text-xs" style={smallBtn(C.green)}><CheckCircle2 size={13} />Approve</button>
              <button type="button" onClick={() => setDialog({ kind: "reject", claim: c })} className="flex min-h-[36px] items-center gap-1.5 px-3 text-xs" style={smallBtn(C.carbon)}><XCircle size={13} />Reject</button>
            </div>
          )}
          {canManage && c.status === "approved" && (
            <button type="button" onClick={() => setDialog({ kind: "resolve", claim: c })} className="mt-2 flex min-h-[36px] items-center gap-1.5 px-3 text-xs" style={smallBtn(C.orange)}><ClipboardCheck size={13} />Mark resolved</button>
          )}
        </div>
      ))}
      {!claims.length && <p className="px-4 py-10 text-center text-sm" style={{ border: `1px dashed ${C.ruleStrong}`, color: C.inkSoft }}>No claims here.</p>}
      {dialog?.kind === "reject" && (
        <Prompt title={`Reject ${dialog.claim.code}`} tone={C.carbon} intro="The customer is told this reason." fields={[{ name: "note", label: "Reason", required: true }]} submitLabel="Reject claim"
          onClose={() => setDialog(null)} onSubmit={async (v) => { await call(`/warranty-claims/${dialog.claim.id}/decide/`, { decision: "reject", note: v.note }); setDialog(null); }} />
      )}
      {dialog?.kind === "resolve" && (
        <Prompt title={`Resolve ${dialog.claim.code}`} intro="Record how it was settled and what it cost you. The customer is told it is complete." submitLabel="Mark resolved"
          fields={[{ name: "resolution", label: "Outcome", type: "select", required: true, options: [{ value: "", label: "Select…" }, { value: "repaired", label: "Repaired" }, { value: "replaced", label: "Replaced" }, { value: "refunded", label: "Refunded" }, { value: "other", label: "Other" }] },
            { name: "cost", label: "Cost to us (₹, 0 if none)", required: true, inputMode: "numeric" }, { name: "repair_code", label: "Repair job code (optional)" }, { name: "note", label: "Note (optional)" }]}
          initial={{ cost: "0" }} onClose={() => setDialog(null)} onSubmit={async (v) => { await call(`/warranty-claims/${dialog.claim.id}/resolve/`, v); setDialog(null); }} />
      )}
    </div>
  );
}
