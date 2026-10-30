import { useState } from "react";
import { Repeat2 } from "lucide-react";
import { C, F, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote } from "../Atoms";

const INTERVALS = [
  [1, "Monthly"], [3, "Every 3 months"], [6, "Every 6 months"], [12, "Every 12 months"],
];

/*
 * The agreement's recurring payment plan: how many months each rent
 * invoice covers (1 / 3 / 6 / 12) and whether the invoice is raised and
 * sent to the client automatically a few days before it falls due.
 * Changing it only affects invoices not raised yet.
 */
export default function RentPaymentPlan({ rental, canManage, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const closed = ["closed", "cancelled", "rejected"].includes(rental.status);
  const next = rental.next_billing_period;

  const save = async (patch) => {
    setBusy(true);
    setError("");
    try {
      onChanged(await api.post(`/rentals/${rental.id}/payment-plan/`, {
        payment_interval_months: rental.payment_interval_months,
        auto_invoice: rental.auto_invoice,
        ...patch,
      }));
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3 py-2" style={{ border: `1px solid ${C.rule}` }}>
      <Repeat2 size={13} style={{ color: C.inkSoft }} />
      <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Recurring payment</span>
      <select value={rental.payment_interval_months ?? 1} disabled={!canManage || closed || busy} aria-label="Billing cycle"
        onChange={(e) => save({ payment_interval_months: +e.target.value })}
        className="bg-transparent px-2 py-1 text-xs outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
        {INTERVALS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <label className="flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        <input type="checkbox" checked={!!rental.auto_invoice} disabled={!canManage || closed || busy}
          onChange={(e) => save({ auto_invoice: e.target.checked })} />
        Send invoice to client automatically
      </label>
      {next && (
        <span className="text-xs" style={{ fontFamily: F.mono, color: C.ink }}>
          next: {next.months} month{next.months > 1 ? "s" : ""} · {money(next.amount)}
        </span>
      )}
      <ErrorNote message={error} />
    </div>
  );
}
