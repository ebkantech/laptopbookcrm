import { useState } from "react";
import { FileText, Send } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";

const STATUS_COLOR = { Paid: C.green, "Payment link sent": C.amber, Overdue: C.carbon, Cancelled: C.inkSoft, Refunded: C.inkSoft };

/*
 * Rent billing for one agreement. Raising an invoice bills the next
 * unbilled month as a new INV number dated today and sends it to the
 * customer; payment is then taken in Sales & Invoices, which updates
 * this agreement's months paid / last payment / late count.
 */
export default function RentInvoices({ rental, canRaise, onChanged }) {
  const [shops, setShops] = useState(null);
  const [shopId, setShopId] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const invoices = rental.rent_invoices || [];
  const next = rental.next_billing_period;
  const billable = ["approved", "active"].includes(rental.status) && next;

  const startRaise = async () => {
    setError("");
    setOpen(true);
    if (!shops) {
      try {
        const all = await api.getAll("/stock-points/");
        setShops(all);
        setShopId(String(all.find((s) => s.kind === "shop")?.id ?? all[0]?.id ?? ""));
      } catch (e) {
        setError(e.message);
      }
    }
  };

  const raise = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/rentals/${rental.id}/raise-invoice/`, { stock_point: +shopId });
      onChanged(res.rental);
      setOpen(false);
      setNote(`${res.invoice_code} raised and sent to the customer — collect payment in Sales & Invoices.`);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!invoices.length && !(canRaise && billable)) return null;

  return (
    <div className="mt-3">
      <Eyebrow>Rent invoices</Eyebrow>
      {invoices.length > 0 && (
        <div className="mt-1.5 space-y-1">
          {invoices.map((inv) => (
            <div key={inv.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 text-xs" style={{ backgroundColor: C.slip2, fontFamily: F.body, color: C.inkSoft }}>
              <span className="flex items-center gap-1.5">
                <FileText size={12} />
                <b style={{ fontFamily: F.mono, color: C.ink }}>{inv.code}</b>
                {inv.period_start && <>· {fmt(inv.period_start)} – {fmt(inv.period_end)}</>}
                · sent {fmt(inv.date)}
              </span>
              <span className="flex items-center gap-2">
                <span style={{ fontFamily: F.mono, color: C.ink }}>{money(inv.total)}</span>
                <Pill color={STATUS_COLOR[inv.status] || C.inkSoft}>{inv.status === "Paid" ? `Paid ${fmt(inv.paid_on)}` : ["Overdue", "Cancelled", "Refunded"].includes(inv.status) ? inv.status : "Awaiting payment"}</Pill>
              </span>
            </div>
          ))}
        </div>
      )}

      {canRaise && billable && !open && (
        <button onClick={startRaise} className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontFamily: F.body, fontWeight: 600 }}>
          <Send size={12} /> Raise rent invoice for {fmt(next.start)} – {fmt(next.end)}
        </button>
      )}
      {canRaise && !next && invoices.length > 0 && (
        <p className="mt-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Every month of the tenure has been invoiced.</p>
      )}

      {open && (
        <div className="mt-2 flex flex-wrap items-end gap-2 p-2" style={{ border: `1px solid ${C.rule}` }}>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Issued by
            <select value={shopId} onChange={(e) => setShopId(e.target.value)} className="mt-1 block px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }}>
              {(shops || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <button onClick={raise} disabled={busy || !shopId} className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy || !shopId ? 0.6 : 1 }}>
            <Send size={12} /> {busy ? "Raising…" : `Raise & send ${money(rental.total_monthly_fee ?? rental.monthly_fee)}`}
          </button>
          <button onClick={() => setOpen(false)} className="text-xs underline" style={{ fontFamily: F.body, color: C.inkSoft }}>Cancel</button>
        </div>
      )}
      {note && <p className="mt-1.5 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
      <ErrorNote message={error} />
    </div>
  );
}
