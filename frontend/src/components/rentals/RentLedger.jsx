import { useEffect, useMemo, useState } from "react";
import { CalendarClock, FileText, X } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import OrderToggle from "../OrderToggle";
import { useOrder } from "../../lib/order";
import { describeRow, groupByClient, grandTotals } from "./ledgerModel";

const TONE_COLOR = { paid: C.green, late: C.amber, due: C.amber, overdue: C.carbon, scheduled: C.inkSoft, muted: C.inkSoft };

/*
 * Rent invoice ledger. One block per rental client with the whole history of
 * their recurring-payment invoices: when each was sent, the period it covers,
 * the amount, the due date and where it stands (paid on time / paid late /
 * due in N days / overdue), plus the invoices still to be sent automatically.
 */
export default function RentLedger({ clients, onClose }) {
  const [rows, setRows] = useState(null);
  const [party, setParty] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [order, setOrder] = useOrder("rentledger", "desc");

  useEffect(() => {
    const qs = new URLSearchParams();
    if (party) qs.set("party", party);
    if (status) qs.set("status", status);
    setRows(null);
    setError("");
    api.get(`/rentals/payment-ledger/?${qs}`).then((d) => setRows(d.results ?? d)).catch((e) => setError(e.message));
  }, [party, status]);

  const groups = useMemo(() => groupByClient(rows || []), [rows]);
  const all = useMemo(() => grandTotals(groups), [groups]);
  const pick = { fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` };
  const mono = { fontFamily: F.mono };

  return (
    <div className="mt-4 rounded-2xl p-4" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
      <div className="flex flex-wrap items-center gap-2">
        <Eyebrow>Rent invoice ledger</Eyebrow>
        <select value={party} onChange={(e) => setParty(e.target.value)} aria-label="Client" className="ml-auto bg-transparent px-2 py-1 text-xs outline-none" style={pick}>
          <option value="">All rental clients</option>
          {clients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status" className="bg-transparent px-2 py-1 text-xs outline-none" style={pick}>
          <option value="">Any status</option>
          <option value="Payment link sent">Unpaid</option>
          <option value="Overdue">Overdue</option>
          <option value="Paid">Paid</option>
          <option value="Scheduled">Scheduled (not sent yet)</option>
        </select>
        <OrderToggle value={order} onChange={setOrder} label="Rent ledger order" />
        <button type="button" onClick={onClose} aria-label="Close ledger"><X size={16} style={{ color: C.inkSoft }} /></button>
      </div>
      <ErrorNote message={error} />
      {!rows ? <p className="mt-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading…</p> : (
        <>
          {groups.length > 0 && (
            <p className="mt-3 text-xs" style={{ ...mono, color: C.inkSoft }} data-testid="ledger-summary">
              {groups.length} client{groups.length > 1 ? "s" : ""} · {all.invoices} invoice{all.invoices === 1 ? "" : "s"} · billed {money(all.invoiced)} · paid {money(all.paid)} · outstanding {money(all.outstanding)}
              {all.overdueCount > 0 && <span style={{ color: C.carbon }}> · overdue {money(all.overdueAmount)}</span>}
            </p>
          )}
          {!groups.length && (
            <p className="mt-3 py-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
              {party || status ? "No rent invoices match these filters." : "No rent invoices sent yet."}
            </p>
          )}
          {groups.map((g) => (
            <section key={g.party} className="mt-3 rounded-xl p-3" style={{ border: `1px solid ${C.rule}` }} data-testid="ledger-client">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h4 className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{g.name}</h4>
                <span className="text-xs" style={{ ...mono, color: C.inkSoft }}>{g.agreements.join(", ") || "—"}{g.phone ? ` · ${g.phone}` : ""}</span>
                <span className="ml-auto text-xs" style={{ ...mono, color: C.inkSoft }}>
                  billed {money(g.totals.invoiced)} · paid {money(g.totals.paid)} · outstanding {money(g.totals.outstanding)}
                  {g.totals.overdueCount > 0 && <span style={{ color: C.carbon }}> · {g.totals.overdueCount} overdue</span>}
                  {g.totals.latePayments > 0 && ` · ${g.totals.latePayments} paid late`}
                </span>
              </div>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                  <thead>
                    <tr style={{ color: C.inkSoft }}>
                      {["Sent on", "Invoice", "Period", "Amount", "Due", "Status"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(order === "desc" ? g.rows : [...g.rows.filter((x) => x.kind !== "scheduled")].reverse().concat(g.rows.filter((x) => x.kind === "scheduled"))).map((r) => {
                      const s = describeRow(r, fmt);
                      const scheduled = r.kind === "scheduled";
                      return (
                        <tr key={r.id} style={{ borderTop: `1px solid ${C.rule}`, opacity: scheduled ? 0.8 : 1 }} data-testid={scheduled ? "ledger-scheduled" : "ledger-invoice"}>
                          <td className="whitespace-nowrap py-1.5 pr-3" style={mono}>{scheduled ? (r.send_on ? fmt(r.send_on) : "manual") : fmt(r.date)}</td>
                          <td className="whitespace-nowrap py-1.5 pr-3" style={mono}>
                            <span className="inline-flex items-center gap-1">{scheduled ? <CalendarClock size={11} /> : <FileText size={11} />}{scheduled ? "upcoming" : r.code}</span>
                          </td>
                          <td className="whitespace-nowrap py-1.5 pr-3" style={mono}>
                            {r.period_start ? `${fmt(r.period_start)} – ${fmt(r.period_end)}` : "—"}{r.months > 1 && ` (${r.months} mo)`}
                          </td>
                          <td className="py-1.5 pr-3" style={mono}>{money(r.total)}</td>
                          <td className="whitespace-nowrap py-1.5 pr-3" style={mono}>{r.due_date ? fmt(r.due_date) : "—"}</td>
                          <td className="py-1.5 pr-3">
                            <Pill color={TONE_COLOR[s.tone]}>{s.label}</Pill>
                            <span className="block" style={{ color: C.inkSoft }}>
                              {s.detail}
                              {!scheduled && r.status === "Paid" && (r.pay_method || r.payment_reference) && ` · ${[r.pay_method, r.payment_reference].filter(Boolean).join(" ")}`}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
