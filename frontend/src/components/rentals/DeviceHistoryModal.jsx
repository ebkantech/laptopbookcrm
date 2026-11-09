import { useEffect, useState } from "react";
import { AlertTriangle, History, Laptop, Users, Wrench, X } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, fmt, money } from "../../lib/theme";
import { ErrorNote, Pill, Spinner } from "../Atoms";

const STATUS_COLOR = { available: C.green, reserved: C.amber, rented: C.blue, maintenance: C.amber, retired: C.inkSoft };
const AGREEMENT_COLOR = { active: C.blue, closed: C.inkSoft, cancelled: C.inkSoft, approved: C.green, pending_approval: C.amber, draft: C.inkSoft, rejected: C.carbon };
const ISSUE_COLOR = { Open: C.carbon, "In progress": C.amber, Resolved: C.green };
const KIND_ICON = { rented: Users, back: Laptop, issue: AlertTriangle, issue_resolved: AlertTriangle, repair: Wrench };
const when = (v) => {
  if (!v) return "";
  // a plain date (YYYY-MM-DD) has no time to show
  return /^\d{4}-\d{2}-\d{2}$/.test(v) ? fmt(v)
    : new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

/*
 * The Device button: one rental laptop's whole life -- every customer who
 * rented it, the problems raised while it was out and who handled them,
 * every repair job on its serial number and the staff who worked on it.
 */
export default function DeviceHistoryModal({ assetId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("customers");

  useEffect(() => {
    api.get(`/rental-assets/${assetId}/history/`).then(setData, (e) => setError(e.body?.detail || e.message));
  }, [assetId]);

  const small = { fontFamily: F.body, color: C.inkSoft };
  const label = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", color: C.inkSoft };
  const box = { backgroundColor: C.slip2, border: `1px solid ${C.rule}` };
  const d = data?.device;
  const s = data?.summary;
  const tabs = data ? [
    ["customers", `Customers (${data.agreements.length})`],
    ["problems", `Problems (${s.problems})`],
    ["repairs", `Repairs (${data.repairs.length})`],
    ["timeline", "Timeline"],
  ] : [];
  const problems = data ? data.agreements.flatMap((a) => a.issues.map((i) => ({ ...i, agreement: a }))) : [];

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={(e) => { e.stopPropagation(); onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Device history" data-panel className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl p-5 sm:rounded-2xl sm:p-6" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-xs uppercase" style={label}><History size={13} /> Device history</span>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        <ErrorNote message={error} />
        {!data && !error && <div className="py-8"><Spinner label="Loading device history…" /></div>}
        {data && (
          <>
            <div className="mt-3 flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-lg" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{d.brand} {d.model_name}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
                  {d.asset_tag} · SN {d.serial_number}{d.product_code ? ` · ${d.product_code}` : ""}{d.variant_code ? ` · SKU ${d.variant_code}` : ""}
                </p>
                <p className="mt-0.5 text-xs" style={small}>
                  In the rental fleet since {fmt(d.added_at)}{d.from_inventory && d.from_store ? `, taken from ${d.from_store} stock` : d.from_store ? ` · ${d.from_store}` : ""}
                </p>
              </div>
              <Pill color={STATUS_COLOR[d.status] || C.inkSoft}>{d.status_label}</Pill>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[["Times rented", s.times_rented], ["Customers", s.customers], ["Problems raised", s.problems], ["Repair jobs", s.repairs]].map(([k, v]) => (
                <div key={k} className="rounded-lg px-3 py-2" style={box}>
                  <p className="text-[10px] uppercase" style={label}>{k}</p>
                  <p className="text-lg" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{v}</p>
                </div>
              ))}
            </div>
            {s.current_customer && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.blue, fontWeight: 600 }}>Now with {s.current_customer}</p>}

            <div className="mt-4 flex flex-wrap gap-1.5" role="tablist">
              {tabs.map(([id, text]) => (
                <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className="rounded-full px-3 py-1 text-xs"
                  style={{ fontFamily: F.body, fontWeight: 600, border: `1px solid ${tab === id ? C.stamp : C.rule}`, color: tab === id ? C.stamp : C.inkSoft, backgroundColor: tab === id ? `${C.stamp}12` : "transparent" }}>
                  {text}
                </button>
              ))}
            </div>

            <div className="mt-3 space-y-2">
              {tab === "customers" && (data.agreements.length ? data.agreements.map((a) => (
                <div key={a.rental_id} className="rounded-xl p-3 text-sm" style={box}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{a.customer}{a.customer_type ? <span className="ml-1 text-xs" style={small}>({a.customer_type})</span> : null}</p>
                      <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{a.agreement_code} · {a.phone}</p>
                    </div>
                    <Pill color={AGREEMENT_COLOR[a.status] || C.inkSoft}>{a.status_label}</Pill>
                  </div>
                  <p className="mt-1.5 text-xs" style={small}>
                    {fmt(a.start)}{a.end ? ` → ${fmt(a.end)}` : ""} · {a.tenure_months} month{a.tenure_months === 1 ? "" : "s"} · {money(a.monthly_fee)}/month
                    {a.devices_on_agreement > 1 ? ` · ${a.devices_on_agreement} devices on this agreement` : ""}
                  </p>
                  {a.handed_over_at && <p className="text-xs" style={small}>Handed over {when(a.handed_over_at)}{a.handed_over_by ? ` by ${a.handed_over_by}` : ""}</p>}
                  {a.closed_at && <p className="text-xs" style={small}>{a.status === "cancelled" ? "Cancelled" : "Returned"} {when(a.closed_at)}</p>}
                  {(a.condition_notes || a.accessories.length > 0) && (
                    <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                      {a.condition_notes ? `Condition at handover: ${a.condition_notes}` : ""}{a.condition_notes && a.accessories.length ? " · " : ""}{a.accessories.length ? `With: ${a.accessories.join(", ")}` : ""}
                    </p>
                  )}
                  {a.issues.length > 0 && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.amber, fontWeight: 600 }}>{a.issues.length} problem{a.issues.length > 1 ? "s" : ""} raised during this rental</p>}
                </div>
              )) : <p className="text-sm" style={small}>This device hasn't been rented out yet.</p>)}

              {tab === "problems" && (problems.length ? problems.map((i) => (
                <div key={i.id} className="rounded-xl p-3 text-sm" style={box}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{i.title}</p>
                    <Pill color={ISSUE_COLOR[i.status] || C.inkSoft}>{i.status}</Pill>
                  </div>
                  {i.description && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.ink }}>{i.description}</p>}
                  <p className="mt-1 text-xs" style={small}>
                    {i.agreement.customer} · {i.agreement.agreement_code} · raised {when(i.raised_at)}
                    {i.resolved_at ? ` · resolved ${when(i.resolved_at)}` : ""}
                  </p>
                  <p className="text-xs" style={{ fontFamily: F.body, color: i.assigned_to ? C.ink : C.amber }}>{i.assigned_to ? `Handled by ${i.assigned_to}` : "Not assigned to anyone yet"}</p>
                  {i.agreement.devices_on_agreement > 1 && <p className="text-[11px]" style={small}>Raised on an agreement with {i.agreement.devices_on_agreement} devices — it may be about another one.</p>}
                </div>
              )) : <p className="text-sm" style={small}>No problems have been raised on this device.</p>)}

              {tab === "repairs" && (data.repairs.length ? data.repairs.map((r) => (
                <div key={r.id} className="rounded-xl p-3 text-sm" style={box}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{r.code}</p>
                    <Pill color={r.status === "Delivered" ? C.green : C.amber}>{r.status}</Pill>
                  </div>
                  <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.ink }}>Problem: {r.problem}</p>
                  {r.diagnosis && <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>Diagnosis: {r.diagnosis}{r.diagnosed_by ? ` (${r.diagnosed_by})` : ""}</p>}
                  <p className="mt-1 text-xs" style={small}>Booked {fmt(r.received)} at {r.store} · for {r.customer}</p>
                  <p className="text-xs" style={{ fontFamily: F.body, color: r.assigned_to ? C.ink : C.amber, fontWeight: 600 }}>
                    <Wrench size={11} className="mr-1 inline" />{r.assigned_to ? `Repair staff: ${r.assigned_to}` : "Not assigned to repair staff yet"}
                    {r.worked_by && r.worked_by !== r.assigned_to ? ` · finished by ${r.worked_by}` : ""}
                  </p>
                </div>
              )) : <p className="text-sm" style={small}>No repair jobs on serial number {d.serial_number}.</p>)}

              {tab === "timeline" && (
                <ol className="relative ml-2 space-y-3 border-l pl-4" style={{ borderColor: C.rule }}>
                  {data.timeline.map((t, n) => {
                    const Icon = KIND_ICON[t.kind] || History;
                    return (
                      <li key={n} className="relative">
                        <span className="absolute -left-[1.6rem] top-0.5 flex h-5 w-5 items-center justify-center rounded-full" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}><Icon size={10} style={{ color: C.inkSoft }} /></span>
                        <p className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{t.text}</p>
                        <p className="text-xs" style={small}>{when(t.at)}{t.by ? ` · ${t.by}` : ""}{t.store ? ` · ${t.store}` : ""}</p>
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
