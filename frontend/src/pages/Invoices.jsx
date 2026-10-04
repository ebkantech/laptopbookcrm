import { useEffect, useState } from "react";
import { Check, IndianRupee, Mail, Plus, Printer, Repeat2, ShieldCheck, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, PillButton, SearchInput, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import PrintableInvoice from "../components/invoices/PrintableInvoice";
import UpiPaymentLink from "../components/invoices/UpiPaymentLink";
import PartyPicker from "../components/invoices/PartyPicker";

const STATUS_COLOR = { Paid: "#36D399", "Payment link sent": "#F5A623", Overdue: "#FB5B5B", Cancelled: "#8A8F98", Refunded: "#7C6FD8" };
const isOutstanding = (inv) => inv.status === "Payment link sent" || inv.status === "Overdue";
const isSettled = (inv) => inv.status === "Paid" || inv.status === "Refunded";
// "Payment link sent" is also the default status of a brand-new unpaid
// invoice, so only say a link was sent when one actually is open.
const STATUS_LABEL = { "Payment link sent": "Awaiting payment" };
const statusLabel = (s) => STATUS_LABEL[s] || s;
const invoiceStatusLabel = (inv) =>
  inv.status === "Payment link sent" && inv.payment_links?.some((l) => l.status === "sent") ? "Payment link sent" : statusLabel(inv.status);
const PAYMENT_METHODS = ["Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"];
const REFERENCE_HINT = {
  UPI: "UPI transaction ID / UTR", "Bank transfer": "UTR / NEFT / IMPS reference", Card: "Card slip / approval code",
  Cheque: "Cheque number and bank", Other: "Reference", Cash: "Receipt number (optional)",
};
const WARRANTY_STATUS_COLOR = { Active: "#36D399", "Expiring soon": "#F5A623", Expired: "#FB5B5B" };

function NewInvoiceModal({ products, stockPoints, onClose, onCreate }) {
  // No default customer: pre-selecting the first name made it easy to
  // bill the wrong person.
  const [party, setParty] = useState(null);
  const [stockPoint, setStockPoint] = useState(stockPoints.find((s) => s.kind === "shop")?.id);
  const blankLine = () => ({ productId: "", variantId: "", qty: 1, price: "" });
  const [lines, setLines] = useState([blankLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const shopSlug = stockPoints.find((s) => s.id === stockPoint)?.slug;
  const variantOf = (line) => products.find((p) => p.id === +line.productId)?.variants.find((v) => v.id === +line.variantId);
  const inStock = (variant) => variant?.stock?.find((s) => s.stock_point === shopSlug)?.quantity ?? 0;
  const setLine = (i, patch) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const pickProduct = (i, productId) => {
    const v = products.find((p) => p.id === +productId)?.variants[0];
    setLine(i, { productId, variantId: v ? String(v.id) : "", price: v ? String(v.sell_price) : "" });
  };
  const pickVariant = (i, variantId) => {
    const v = products.find((p) => p.id === +lines[i].productId)?.variants.find((x) => x.id === +variantId);
    setLine(i, { variantId, price: v ? String(v.sell_price) : "" });
  };
  const total = lines.reduce((sum, l) => sum + (+l.price || 0) * (+l.qty || 0), 0);

  const submit = async () => {
    setError("");
    if (!party) return setError("Pick or add the customer.");
    const filled = lines.filter((l) => l.variantId);
    if (!filled.length) return setError("Add at least one product.");
    for (const l of filled) {
      const v = variantOf(l);
      if (!(+l.qty >= 1)) return setError("Every line needs a quantity of at least 1.");
      if (l.price === "" || +l.price < 0) return setError(`Enter a price for ${v?.spec || "each line"}.`);
    }
    setBusy(true);
    try {
      await onCreate({
        party, stock_point: stockPoint, date: new Date().toISOString().slice(0, 10),
        items: filled.map((l) => ({ variant: +l.variantId, qty: +l.qty, price: +l.price })),
      });
    } catch (e) {
      const body = e.body || {};
      setError([].concat(body.items || body.detail || e.message).join(" · "));
    } finally {
      setBusy(false);
    }
  };

  const field = { fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, background: C.slip };
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `2px solid ${C.ruleStrong || C.rule}`, boxShadow: "0 10px 30px rgba(0,0,0,0.5)" }}>
        <div className="flex items-center justify-between"><span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>New sale invoice</span><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>

        <div className="mt-4 space-y-3">
          <div className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            <span className="mb-1 block">Customer</span>
            <PartyPicker value={party} onChange={setParty} />
          </div>
          <label className="text-xs" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>Sold through (stock is taken from here)
            <select value={stockPoint} onChange={(e) => setStockPoint(+e.target.value)} className="mt-1 w-full py-2 text-sm outline-none" style={field}>
              {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>

          <div>
            <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Items</span>
            <div className="mt-1 space-y-2">
              {lines.map((l, i) => {
                const product = products.find((p) => p.id === +l.productId);
                const v = variantOf(l);
                const have = v ? inStock(v) : null;
                const short = v && +l.qty > have;
                return (
                  <div key={i} className="grid grid-cols-[1fr_1fr_64px_100px_24px] items-start gap-2">
                    <select value={l.productId} onChange={(e) => pickProduct(i, e.target.value)} className="py-1.5 text-sm outline-none" style={field}>
                      <option value="">Product…</option>
                      {products.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                    </select>
                    <div>
                      <select value={l.variantId} onChange={(e) => pickVariant(i, e.target.value)} disabled={!product} className="w-full py-1.5 text-sm outline-none" style={field}>
                        {product?.variants.map((x) => <option key={x.id} value={x.id}>{x.spec}</option>)}
                      </select>
                      {v && <span className="text-[11px]" style={{ fontFamily: F.mono, color: short ? C.carbon : C.inkSoft }}>{have} in stock here</span>}
                    </div>
                    <input type="number" min={1} value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} title="Quantity" className="py-1.5 text-center text-sm outline-none" style={{ ...field, fontFamily: F.mono, borderColor: short ? C.carbon : C.rule }} />
                    <input value={l.price} onChange={(e) => setLine(i, { price: e.target.value.replace(/\D/g, "") })} placeholder="₹ each" title="Unit price -- edit for a discount" className="py-1.5 text-right text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
                    <button type="button" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} className="pt-2" title="Remove line"><X size={14} style={{ color: C.inkSoft }} /></button>
                  </div>
                );
              })}
            </div>
            <button type="button" onClick={() => setLines((ls) => [...ls, blankLine()])} className="mt-2 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}><Plus size={12} /> Add another item</button>
            <p className="mt-1 text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>The unit price starts at the list price — change it to give a discount.</p>
          </div>

          <div className="flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
            <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total</span>
            <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(total)}</span>
          </div>
        </div>

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-5 flex w-full items-center justify-center gap-2 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <Plus size={13} /> {busy ? "Creating…" : "Generate invoice"}
        </button>
      </div>
    </div>
  );
}

function WarrantyCard({ invoice, warranty, onGranted }) {
  const { can } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [term, setTerm] = useState(365);

  const grant = async () => {
    setBusy(true);
    setError("");
    const start = invoice.date;
    const d = new Date(start);
    d.setDate(d.getDate() + term);
    try {
      const w = await api.post("/warranties/", {
        party: invoice.party, section: "Sales",
        item_label: invoice.items.map((i) => i.product_name).join(", "),
        invoice: invoice.id, start_date: start, end_date: d.toISOString().slice(0, 10),
      });
      onGranted(w);
    } catch (e) {
      setError(e.body?.invoice?.[0] || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!warranty) {
    if (invoice.status !== "Paid") return null;
    return (
      <div className="mt-4 p-3" data-panel style={{ border: `2px dashed ${C.ruleStrong || C.rule}` }}>
        <Eyebrow>Warranty</Eyebrow>
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No warranty raised for this invoice yet.</p>
        {can("warranty.manage") && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select value={term} onChange={(e) => setTerm(+e.target.value)} className="bg-transparent px-2 py-1.5 text-xs outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              <option value={90}>90 days</option>
              <option value={182}>6 months</option>
              <option value={365}>1 year</option>
            </select>
            <button onClick={grant} disabled={busy} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
              <ShieldCheck size={12} /> {busy ? "Granting…" : "Grant warranty"}
            </button>
          </div>
        )}
        <ErrorNote message={error} />
      </div>
    );
  }

  return (
    <div className="mt-4 p-3" data-panel style={{ border: `2px solid ${C.green}`, backgroundColor: `${C.green}14`, boxShadow: "0 6px 18px rgba(0,0,0,0.35)" }}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: C.inkSoft }}>
          <ShieldCheck size={13} style={{ color: C.green }} /> Warranty terms & conditions
        </span>
        <Pill color={WARRANTY_STATUS_COLOR[warranty.status]}>{warranty.status}</Pill>
      </div>
      <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{fmt(warranty.start_date)} → {fmt(warranty.end_date)}</p>
      <p className="mt-2 text-xs leading-relaxed" style={{ fontFamily: F.body, color: C.ink }}>{warranty.terms_text}</p>
      <p className="mt-2 flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        <Mail size={11} /> Emailed to {warranty.party_email || "customer on file"}
      </p>
    </div>
  );
}

/* Recording a payment received outside any gateway -- the method and
 * the reference (UTR, cheque no. ...) are what let anyone match this
 * invoice against the bank/UPI statement later. */
function RecordPayment({ invoice, onSettle }) {
  const [method, setMethod] = useState("UPI");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    if (method !== "Cash" && !reference.trim()) return setError(`Enter the ${REFERENCE_HINT[method]} so this payment can be traced.`);
    setBusy(true);
    try {
      await onSettle(invoice.id, { pay_method: method, payment_reference: reference.trim(), paid_on: paidOn });
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const field = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };
  return (
    <div className="mt-3 p-3" data-panel style={{ border: `1px solid ${C.rule}` }}>
      <Eyebrow>Record payment received</Eyebrow>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Method
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field}>
            {PAYMENT_METHODS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Paid on
          <input type="date" value={paidOn} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setPaidOn(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
        <label className="block text-xs sm:col-span-2" style={{ fontFamily: F.body, color: C.inkSoft }}>{REFERENCE_HINT[method]}
          <input value={reference} maxLength={80} onChange={(e) => setReference(e.target.value)} placeholder={method === "Cash" ? "Optional" : "Required"} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
      </div>
      <ErrorNote message={error} />
      <button onClick={submit} disabled={busy} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
        <Check size={12} /> {busy ? "Saving…" : `Mark paid — ${money(invoice.total)}`}
      </button>
    </div>
  );
}

/* Cancel an unpaid invoice raised by mistake -- a reason is required and
 * recorded; a sale's items go back into stock. */
function CancelInvoice({ invoice, onChanged }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mt-3 text-xs underline" style={{ fontFamily: F.body, color: C.carbon }}>Cancel this invoice…</button>
    );
  }
  const submit = async () => {
    if (!reason.trim()) return setError("Say why it's being cancelled.");
    setBusy(true);
    setError("");
    try {
      onChanged(await api.post(`/invoices/${invoice.id}/cancel/`, { reason: reason.trim() }));
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-3 p-3" style={{ border: `1px solid ${C.carbon}55`, backgroundColor: `${C.carbon}0A` }}>
      <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>
        Cancel {invoice.code}? {invoice.source === "sale" ? "The items go back into stock. " : ""}Any payment link sent for it stops working.
      </p>
      <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder="Reason, e.g. wrong item billed" className="mt-2 w-full px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }} />
      <ErrorNote message={error} />
      <div className="mt-2 flex gap-2">
        <button onClick={submit} disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.carbon, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>{busy ? "Cancelling…" : "Cancel invoice"}</button>
        <button onClick={() => setOpen(false)} className="text-xs underline" style={{ fontFamily: F.body, color: C.inkSoft }}>Keep it</button>
      </div>
    </div>
  );
}

/* Pay money back on a paid invoice. A sale is refunded by returning
 * items (they go back into stock unless damaged); anything else by an
 * amount. The refund goes out of the cash or bank book. */
function RefundInvoice({ invoice, onChanged }) {
  const [open, setOpen] = useState(false);
  const isSale = invoice.source === "sale";
  const [qty, setQty] = useState({});
  const [amount, setAmount] = useState("");
  const [restock, setRestock] = useState(true);
  const [method, setMethod] = useState(invoice.pay_method && PAYMENT_METHODS.includes(invoice.pay_method) ? invoice.pay_method : "Cash");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const left = invoice.total - (invoice.refunded_total || 0);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mt-3 text-xs underline" style={{ fontFamily: F.body, color: C.carbon }}>
        {isSale ? "Return items / refund…" : "Refund…"}
      </button>
    );
  }
  const returnable = invoice.items.filter((it) => it.qty - (it.returned_qty || 0) > 0);
  const value = isSale ? invoice.items.reduce((sum, it) => sum + (Number(qty[it.id]) || 0) * it.price, 0) : Number(amount) || 0;
  const field = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };

  const submit = async () => {
    setError("");
    if (value <= 0) return setError(isSale ? "Choose how many of which item are coming back." : "Enter the amount to refund.");
    if (value > left) return setError(`Only ${money(left)} is left to refund on this invoice.`);
    if (!reason.trim()) return setError("Say why the money is being refunded.");
    if (method !== "Cash" && !reference.trim()) return setError(`Enter the ${REFERENCE_HINT[method]} of the refund.`);
    setBusy(true);
    try {
      const body = { method, reference: reference.trim(), reason: reason.trim() };
      if (isSale) {
        body.items = Object.entries(qty).filter(([, q]) => Number(q) > 0).map(([item, q]) => ({ item: Number(item), qty: Number(q) }));
        body.restock = restock;
      } else {
        body.amount = Number(amount);
      }
      onChanged(await api.post(`/invoices/${invoice.id}/refund/`, body));
      setOpen(false);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 p-3" style={{ border: `1px solid ${C.carbon}55`, backgroundColor: `${C.carbon}0A` }}>
      <Eyebrow>{isSale ? "Return items & refund" : "Refund"}</Eyebrow>
      {isSale ? (
        <div className="mt-2 space-y-1.5">
          {returnable.map((it) => {
            const max = it.qty - (it.returned_qty || 0);
            return (
              <div key={it.id} className="flex items-center justify-between gap-2 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                <span>{it.product_name} <span style={{ fontFamily: F.mono, color: C.inkSoft }}>· {money(it.price)} each · {max} returnable</span></span>
                <input type="number" min={0} max={max} value={qty[it.id] ?? ""} placeholder="0" title="Quantity returned"
                  onChange={(e) => setQty({ ...qty, [it.id]: Math.max(0, Math.min(max, Number(e.target.value.replace(/\D/g, "")) || 0)) })}
                  className="w-16 px-2 py-1 text-right text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
              </div>
            );
          })}
          <label className="flex items-center gap-2 text-xs" style={{ display: "flex", fontFamily: F.body, color: C.ink }}>
            <input type="checkbox" checked={restock} onChange={(e) => setRestock(e.target.checked)} />
            Put the returned units back into stock at {invoice.stock_point_name} (untick if damaged)
          </label>
        </div>
      ) : (
        <label className="mt-2 text-xs" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>Amount (₹) — up to {money(left)}
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
      )}
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="text-xs" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>Paid back by
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field}>
            {PAYMENT_METHODS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label className="text-xs" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>{REFERENCE_HINT[method]}
          <input value={reference} maxLength={80} onChange={(e) => setReference(e.target.value)} placeholder={method === "Cash" ? "Optional" : "Required"} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
        <label className="text-xs sm:col-span-2" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>Reason
          <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="e.g. faulty unit returned within 7 days" className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field} />
        </label>
      </div>
      <ErrorNote message={error} />
      <div className="mt-2 flex gap-2">
        <button onClick={submit} disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.carbon, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>
          {busy ? "Refunding…" : `Refund ${money(value)}`}
        </button>
        <button onClick={() => setOpen(false)} className="text-xs underline" style={{ fontFamily: F.body, color: C.inkSoft }}>Close</button>
      </div>
    </div>
  );
}

function RefundHistory({ invoice }) {
  if (!invoice.refunds?.length) return null;
  return (
    <div className="mt-3 space-y-1">
      {invoice.refunds.map((r) => (
        <div key={r.id} className="px-3 py-2 text-xs" style={{ backgroundColor: C.slip2, fontFamily: F.body, color: C.inkSoft }}>
          <span style={{ fontFamily: F.mono, color: C.carbon, fontWeight: 600 }}>− {money(r.amount)}</span> refunded {fmt(r.refunded_on)} via <b style={{ color: C.ink }}>{r.method}</b>
          {r.reference && <> · ref <span style={{ fontFamily: F.mono, color: C.ink }}>{r.reference}</span></>} · by {r.by_name} — “{r.reason}”
          {r.items.length > 0 && <div className="mt-0.5">Returned: {r.items.map((i) => `${i.qty} × ${i.label}`).join(", ")}{r.restocked ? " · back in stock" : " · not restocked"}</div>}
        </div>
      ))}
    </div>
  );
}

function InvoiceDetail({ invoice, onClose, onSettle, onChanged }) {
  const { can } = useSession();
  const [warranty, setWarranty] = useState(undefined); // undefined = loading, null = none
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    api.get(`/warranties/?invoice=${invoice.id}`).then((d) => {
      const rows = d.results ?? d;
      setWarranty(rows[0] || null);
    });
  }, [invoice.id]);

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `2px solid ${C.ruleStrong || C.rule}`, boxShadow: "0 10px 30px rgba(0,0,0,0.5)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{invoice.code}</p>
            <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{invoice.party_name} · {fmt(invoice.date)} · {invoice.stock_point_name}</p>
            {invoice.reference && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.ink }}>{invoice.source_label}: {invoice.reference}</p>}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setPrinting(true)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, fontWeight: 600, color: C.ink }}>
              <Printer size={12} /> Print
            </button>
            <button onClick={onClose}><X size={18} style={{ color: C.inkSoft }} /></button>
          </div>
        </div>

        <div className="mt-4 space-y-1.5">
          {invoice.items.map((it) => (
            <div key={it.id} className="flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{it.product_name} <span style={{ fontFamily: F.mono, color: C.inkSoft, fontSize: 11 }}>{it.qty} × {money(it.price)}</span></span>
              <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(it.price * it.qty)}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between px-3 py-2" data-panel style={{ border: `2px solid ${C.rule}` }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(invoice.total)}</span>
        </div>
        {invoice.refunded_total > 0 && (
          <div className="mt-1 flex items-center justify-between px-3 py-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
            <span style={{ fontFamily: F.body }}>Refunded {money(invoice.refunded_total)} · kept</span>
            <span style={{ color: C.ink, fontWeight: 700 }}>{money(invoice.net_total)}</span>
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Pill color={STATUS_COLOR[invoice.status]}>{invoiceStatusLabel(invoice)}</Pill>
          {invoice.due_date && isOutstanding(invoice) && (
            <span className="text-xs" style={{ fontFamily: F.mono, color: invoice.status === "Overdue" ? C.carbon : C.inkSoft }}>due {fmt(invoice.due_date)}</span>
          )}
        </div>
        {invoice.status === "Cancelled" ? (
          <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            Cancelled {fmt(invoice.cancelled_at)}{invoice.cancelled_by_name ? ` by ${invoice.cancelled_by_name}` : ""} — “{invoice.cancel_reason}”.
            {invoice.source === "sale" ? " The items went back into stock." : ""}
          </p>
        ) : isSettled(invoice) ? (
          invoice.paid_on ? (
            <p className="mt-2 flex flex-wrap items-center gap-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
              <IndianRupee size={11} /> Paid {fmt(invoice.paid_on)} via <b style={{ color: C.ink }}>{invoice.pay_method}</b>
              {invoice.payment_reference && <> · ref <span style={{ fontFamily: F.mono, color: C.ink }}>{invoice.payment_reference}</span></>}
              {invoice.settled_by_name && <> · recorded by {invoice.settled_by_name}</>}
            </p>
          ) : (
            <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Marked paid before payment details were recorded{invoice.pay_method ? ` (${invoice.pay_method})` : ""}.</p>
          )
        ) : can("invoices.settle") && <RecordPayment invoice={invoice} onSettle={onSettle} />}
        {invoice.status !== "Cancelled" && <UpiPaymentLink invoice={invoice} onChanged={onChanged} />}
        {isOutstanding(invoice) && can("invoices.create") && <CancelInvoice invoice={invoice} onChanged={onChanged} />}
        <RefundHistory invoice={invoice} />
        {invoice.status === "Paid" && invoice.total > 0 && can("invoices.refund") && <RefundInvoice key={invoice.refunds?.length || 0} invoice={invoice} onChanged={onChanged} />}

        {invoice.source === "sale" && (warranty === undefined ? <div className="mt-4"><Spinner /></div> : <WarrantyCard invoice={invoice} warranty={warranty} onGranted={setWarranty} />)}
      </div>
      {printing && <PrintableInvoice invoiceId={invoice.id} onClose={() => setPrinting(false)} />}
    </div>
  );
}

const SOURCE_TABS = [
  { id: "all", label: "All" },
  { id: "sale", label: "Sales" },
  { id: "repair", label: "Repairs" },
  { id: "rental", label: "Rentals" },
];
const SOURCE_COLOR = { sale: C.stamp, repair: C.amber, rental: C.blue };

/*
 * Every invoice the business raises -- product sales, repair jobs and
 * rental rent -- is listed and paid here. Repairs and Rentals raise
 * their invoices from their own screens; payment is only ever taken
 * on this screen.
 */
export default function Invoices() {
  const { can } = useSession();
  const [invoices, setInvoices] = useState(null);
  const [products, setProducts] = useState([]);
  const [stockPoints, setStockPoints] = useState([]);
  const [error, setError] = useState("");
  const [source, setSource] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [openInvoice, setOpenInvoice] = useState(null);

  useEffect(() => {
    api.getAll("/invoices/").then(setInvoices).catch((e) => setError(e.message));
    // Only products that have something sellable: stock and prices live
    // on variants, so a product with none yet can't go on an invoice.
    api.getAll("/products/").then((all) => setProducts(all.filter((p) => p.variants.length)));
    api.get("/stock-points/").then((d) => setStockPoints(d.results ?? d));
  }, []);

  const create = async (payload) => {
    const inv = await api.post("/invoices/", payload);
    setInvoices((l) => [inv, ...l]);
    setAdding(false);
  };

  const replaceInvoice = (inv) => {
    setInvoices((l) => l.map((i) => (i.id === inv.id ? inv : i)));
    setOpenInvoice((cur) => (cur?.id === inv.id ? inv : cur));
  };

  const settle = async (id, payment) => {
    replaceInvoice(await api.post(`/invoices/${id}/settle/`, payment));
  };

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!invoices) return <Spinner label="Loading invoices…" />;

  // All filtering is client-side -- the full ledger is already loaded.
  const q = query.trim().toLowerCase();
  const bySource = source === "all" ? invoices : invoices.filter((inv) => inv.source === source);
  const byStatus = statusFilter === "all" ? bySource : bySource.filter((inv) => inv.status === statusFilter);
  const visibleInvoices = q
    ? byStatus.filter((inv) => inv.code.toLowerCase().includes(q) || inv.party_name.toLowerCase().includes(q) || (inv.reference || "").toLowerCase().includes(q))
    : byStatus;
  const awaiting = bySource.filter(isOutstanding);
  const count = (id) => (id === "all" ? invoices.length : invoices.filter((inv) => inv.source === id).length);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="px-5 pt-6 sm:px-8">
        <PageHeader title="Sales & Invoices" subtitle="Every invoice — sales, repairs and rentals — and every payment, in one place" />
      </div>
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
        <div className="flex flex-col gap-2">
          <div className="overflow-x-auto">
            <TabBar tabs={SOURCE_TABS.map((t) => ({ id: t.id, label: `${t.label} (${count(t.id)})` }))} value={source} onChange={setSource} />
          </div>
          <div className="overflow-x-auto">
            <TabBar
              tabs={["all", "Paid", "Payment link sent", "Overdue", "Refunded", "Cancelled"].map((s) => ({ id: s, label: s === "all" ? "Any status" : statusLabel(s) }))}
              value={statusFilter}
              onChange={setStatusFilter}
            />
          </div>
        </div>
        {can("invoices.create") && (
          <PillButton icon={Plus} primary onClick={() => setAdding(true)}>New sale invoice</PillButton>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-3 px-5 pb-4 sm:px-8">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by invoice code, customer, ticket or agreement" />
        <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          To collect: <b style={{ fontFamily: F.mono, color: C.ink }}>{money(awaiting.reduce((sum, inv) => sum + inv.total, 0))}</b> across {awaiting.length} invoice{awaiting.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-4 sm:px-8">
        <div className="flex flex-col gap-2.5">
          {visibleInvoices.map((inv) => (
            <div key={inv.id} data-listcard onClick={() => setOpenInvoice(inv)} className="flex flex-wrap items-center gap-3 px-5 py-3.5 cursor-pointer">
              <div className="min-w-[140px] flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{inv.code}</span>
                  <Pill color={SOURCE_COLOR[inv.source]}>{inv.source_label}</Pill>
                  {inv.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{inv.recurring_interval}</Pill>}
                </div>
                <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  {inv.party_name} · {fmt(inv.date)}{inv.reference ? ` · ${inv.reference}` : ""}
                </p>
              </div>
              <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.stock_point_name}</span>
              <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink, minWidth: 96, textAlign: "right" }}>{money(inv.total)}</span>
              <Pill color={STATUS_COLOR[inv.status]}>{invoiceStatusLabel(inv)}</Pill>
              {isOutstanding(inv) && can("invoices.settle") && (
                <button onClick={(e) => { e.stopPropagation(); setOpenInvoice(inv); }} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
                  <IndianRupee size={11} /> Record payment
                </button>
              )}
            </div>
          ))}
          {!visibleInvoices.length && (
            <p className="px-3 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
              {invoices.length ? "No invoices match these filters." : "No invoices yet."}
            </p>
          )}
        </div>
      </div>

      {adding && <NewInvoiceModal products={products} stockPoints={stockPoints} onClose={() => setAdding(false)} onCreate={create} />}
      {openInvoice && <InvoiceDetail invoice={openInvoice} onClose={() => setOpenInvoice(null)} onSettle={settle} onChanged={replaceInvoice} />}
    </div>
  );
}
