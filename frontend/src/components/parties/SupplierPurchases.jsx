import { Fragment, useEffect, useState } from "react";
import { ChevronDown, IndianRupee, PackageSearch } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, fmt, money, todayISO } from "../../lib/theme";
import { ErrorNote, Pill, Spinner } from "../Atoms";

/*
 * A supplier's purchase history (their "ledger" here): every bill line --
 * product, quantity, price paid -- and what those units have earned since:
 * how many are sold, for how much, and the profit over what was paid.
 */
export default function SupplierPurchases({ supplierId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null); // purchase id showing its serial numbers
  const [paying, setPaying] = useState(null); // the "Pay supplier" form
  const [payError, setPayError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const startPay = () => {
    setPayError(""); setNote("");
    setPaying({ amount: data.owed.balance > 0 ? String(data.owed.balance) : "", paid_on: todayISO(), method: "Cash", reference: "", note: "", purchase: "" });
  };
  const pay = async (e) => {
    e.preventDefault();
    if (!(Number(paying.amount) > 0)) return setPayError("Enter the amount paid.");
    setBusy(true); setPayError("");
    try {
      const fresh = await api.post(`/purchases/supplier/${supplierId}/pay/`, {
        amount: Number(paying.amount), paid_on: paying.paid_on, method: paying.method, reference: paying.reference.trim(),
        note: paying.note.trim(), purchase: paying.purchase ? Number(paying.purchase) : null,
      });
      setData((d) => ({ ...fresh, can_pay: d.can_pay }));
      setNote(`${money(Number(paying.amount))} paid by ${paying.method} — recorded in the ${paying.method === "Cash" ? "cash" : "bank"} book.`);
      setPaying(null);
    } catch (err) {
      const b = err.body || {};
      setPayError([].concat(b.amount || [], b.paid_on || [], b.method || [], b.purchase || [], b.detail || []).join(" ") || err.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    api.get(`/purchases/supplier/${supplierId}/`).then(setData, (e) => setError(e.status === 403 ? "Your role can't see purchase prices." : e.message));
  }, [supplierId]);

  const label = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", color: C.inkSoft };
  const cell = "px-2 py-2 text-right text-xs";
  if (error) return <div className="mt-6"><ErrorNote message={error} /></div>;
  if (!data) return <div className="mt-6"><Spinner label="Loading purchases…" /></div>;
  const t = data.totals;
  const owed = data.owed || { bills: 0, paid: 0, balance: 0 };
  const input = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };

  return (
    <section aria-label="Purchases from this supplier" className="mt-6">
      {/* what we owe them: bills minus payments -- kept in step with the cash / bank book */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3" style={{ border: `1px solid ${owed.balance > 0 ? C.carbon : C.rule}`, backgroundColor: C.slip2 }}>
        <div>
          <p className="text-[10px] uppercase" style={label}>{owed.balance > 0 ? "We owe this supplier" : owed.balance < 0 ? "Advance with this supplier" : "Supplier account"}</p>
          <p className="text-xl" style={{ fontFamily: F.mono, fontWeight: 700, color: owed.balance > 0 ? C.carbon : owed.balance < 0 ? C.amber : C.green }}>
            {owed.balance === 0 ? "Settled" : money(Math.abs(owed.balance))}
          </p>
          <p className="text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>Bills {money(owed.bills)} · paid {money(owed.paid)}</p>
        </div>
        {data.can_pay && !paying && (
          <button type="button" onClick={startPay} className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 700, backgroundColor: C.green, color: C.onAccent }}>
            <IndianRupee size={13} /> Pay supplier
          </button>
        )}
      </div>
      {note && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
      {paying && (
        <form onSubmit={pay} className="mt-2 rounded-xl p-3" style={{ border: `1px solid ${C.green}`, backgroundColor: C.slip2 }}>
          <p className="text-[10px] uppercase" style={label}>Pay {data.supplier.name}</p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Amount (₹) *
              <input value={paying.amount} inputMode="numeric" autoFocus onChange={(e) => setPaying({ ...paying, amount: e.target.value.replace(/\D/g, "") })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Paid on *
              <input type="date" value={paying.paid_on} max={todayISO()} onChange={(e) => setPaying({ ...paying, paid_on: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input} />
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Paid by *
              <select value={paying.method} onChange={(e) => setPaying({ ...paying, method: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input}>
                {["Cash", "UPI", "Bank transfer", "Cheque", "Card", "Other"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{paying.method === "Cheque" ? "Cheque no." : "Reference (UTR / receipt)"}
              <input value={paying.reference} maxLength={80} onChange={(e) => setPaying({ ...paying, reference: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input} />
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Against bill (optional)
              <select value={paying.purchase} onChange={(e) => setPaying({ ...paying, purchase: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input}>
                <option value="">Their account in general</option>
                {data.purchases.filter((p) => !p.already_paid).map((p) => <option key={p.id} value={p.id}>{fmt(p.purchased_on)} · {p.bill_no || "no bill no."} · {money(p.amount)}</option>)}
              </select>
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Note
              <input value={paying.note} maxLength={200} onChange={(e) => setPaying({ ...paying, note: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input} />
            </label>
          </div>
          {Number(paying.amount) > owed.balance && owed.balance >= 0 && Number(paying.amount) > 0 && (
            <p className="mt-1.5 text-[11px]" style={{ fontFamily: F.body, color: C.amber }}>That's more than is owed — the extra {money(Number(paying.amount) - Math.max(owed.balance, 0))} stays as an advance with them.</p>
          )}
          <ErrorNote message={payError} />
          <div className="mt-2 flex items-center gap-2">
            <button type="submit" disabled={busy} className="rounded-lg px-3 py-1.5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, backgroundColor: C.green, color: C.onAccent, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Record payment"}</button>
            <button type="button" onClick={() => setPaying(null)} className="text-xs underline" style={{ fontFamily: F.body, color: C.inkSoft }}>Cancel</button>
          </div>
        </form>
      )}

      {data.ledger?.length > 0 && (
        <>
          <p className="mt-4 text-xs uppercase" style={label}>Supplier ledger</p>
          <div className="mt-2 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
            <table className="w-full min-w-[600px] border-collapse">
              <thead style={{ backgroundColor: C.slip2 }}>
                <tr className="text-[10px] uppercase" style={label}>
                  <th className="px-2 py-2 text-left">Date</th><th className="px-2 py-2 text-left">Details</th>
                  <th className="px-2 py-2 text-right">Bill</th><th className="px-2 py-2 text-right">Paid</th><th className="px-2 py-2 text-right">Balance owed</th>
                </tr>
              </thead>
              <tbody>
                {data.ledger.map((e) => (
                  <tr key={e.id} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, fontFamily: F.mono, color: C.ink }}>
                    <td className="px-2 py-2 text-left text-xs">{fmt(e.date)}</td>
                    <td className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>
                      {e.text}{e.note && <span className="block text-[11px]" style={{ color: C.inkSoft }}>{e.note}</span>}
                    </td>
                    <td className={cell}>{e.bill ? money(e.bill) : "—"}</td>
                    <td className={cell} style={{ color: e.paid ? C.green : undefined }}>{e.paid ? money(e.paid) : "—"}</td>
                    <td className={cell} style={{ fontWeight: 700, color: e.balance > 0 ? C.carbon : e.balance < 0 ? C.amber : C.green }}>{money(e.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-5 flex items-center gap-1.5 text-xs uppercase" style={label}><PackageSearch size={13} /> Bought from this supplier</p>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["Bought", `${t.qty} unit${t.qty === 1 ? "" : "s"}`], ["Bought for", money(t.amount)], ["Sold so far", `${t.sold} for ${money(t.sold_for)}`],
          ["Profit on sold units", money(t.profit)]].map(([k, v]) => (
          <div key={k} className="rounded-lg px-3 py-2" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}>
            <p className="text-[10px] uppercase" style={label}>{k}</p>
            <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: k.startsWith("Profit") ? (t.profit >= 0 ? C.green : C.carbon) : C.ink }}>{v}</p>
          </div>
        ))}
      </div>
      {data.purchases.length ? (
        <div className="mt-3 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
          <table className="w-full min-w-[720px] border-collapse">
            <thead style={{ backgroundColor: C.slip2 }}>
              <tr className="text-[10px] uppercase" style={label}>
                <th className="px-2 py-2 text-left">Date · bill</th><th className="px-2 py-2 text-left">Product</th>
                <th className="px-2 py-2 text-right">Qty</th><th className="px-2 py-2 text-right">Price / unit</th><th className="px-2 py-2 text-right">Amount</th>
                <th className="px-2 py-2 text-right">Sold</th><th className="px-2 py-2 text-right">Profit</th>
              </tr>
            </thead>
            <tbody>
              {data.purchases.map((p) => (
                <Fragment key={p.id}>
                  <tr className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, fontFamily: F.mono, color: C.ink }}>
                    <td className="px-2 py-2 text-left text-xs">
                      {fmt(p.purchased_on)}
                      <span className="block text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>{p.bill_no ? `Bill ${p.bill_no}` : "No bill no."} · {p.store}</span>
                      {p.tagged && <span className="mt-0.5 inline-block"><Pill color={C.inkSoft}>added later</Pill></span>}
                    </td>
                    <td className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>
                      {p.product} <span style={{ color: C.inkSoft }}>({p.spec})</span>
                      {p.serials.length > 0 && (
                        <button type="button" onClick={() => setOpen(open === p.id ? null : p.id)} className="mt-0.5 flex items-center gap-0.5 text-[11px] underline" style={{ color: C.stamp }}>
                          {open === p.id ? "Hide" : "Show"} {p.serials.length} serial no.<ChevronDown size={11} style={{ transform: open === p.id ? "rotate(180deg)" : "none" }} />
                        </button>
                      )}
                    </td>
                    <td className={cell}>{p.qty}</td>
                    <td className={cell}>{money(p.unit_cost)}</td>
                    <td className={cell}>{money(p.amount)}</td>
                    <td className={cell}>{p.sold}{p.in_stock ? <span className="block text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>{p.in_stock} in stock</span> : null}</td>
                    <td className={cell} style={{ fontWeight: 700, color: p.sold ? (p.profit >= 0 ? C.green : C.carbon) : C.inkSoft }}>{p.sold ? money(p.profit) : "—"}</td>
                  </tr>
                  {open === p.id && (
                    <tr><td colSpan={7} className="px-2 pb-2 text-[11px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.serials.join(" · ")}</td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: `2px solid ${C.ink}`, fontFamily: F.mono, fontWeight: 700, color: C.ink }}>
                <td className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>Total</td><td />
                <td className={cell}>{t.qty}</td><td /><td className={cell}>{money(t.amount)}</td><td className={cell}>{t.sold}</td>
                <td className={cell} style={{ color: t.profit >= 0 ? C.green : C.carbon }}>{money(t.profit)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Nothing recorded from this supplier yet. Choose them under “Bought from” when adding stock, or use “Set supplier” on a product in Inventory for stock you already have.
        </p>
      )}
    </section>
  );
}
