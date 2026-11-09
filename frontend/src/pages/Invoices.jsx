import { useEffect, useRef, useState } from "react";
import { Check, IndianRupee, Mail, PencilLine, Plus, Printer, Repeat2, ShieldCheck, X } from "lucide-react";
import { C, F, fmt, money, todayISO } from "../lib/theme";
import { api } from "../lib/api";
import { toast } from "../lib/toast";
import { onStoreChanged } from "../lib/storeEvents";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, PillButton, SearchInput, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import OrderToggle from "../components/OrderToggle";
import { orderRows, useOrder } from "../lib/order";
import PrintableInvoice from "../components/invoices/PrintableInvoice";
import UpiPaymentLink from "../components/invoices/UpiPaymentLink";
import PartyPicker from "../components/invoices/PartyPicker";
import SerialPicker from "../components/serials/SerialPicker";
import { WARRANTY_CHOICES, blankLine, discountOff, placeVariant, variantForProduct, warrantyLabel } from "../components/invoices/saleLines";
import ProductSearch from "../components/invoices/ProductSearch";
import { canRevise, revisionLines, unitsOnInvoice } from "../components/invoices/invoiceRevision";

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

// New sale invoice, or -- given `revising` -- the same form filled from an
// unpaid sale invoice, saved back onto it (same number; the server moves
// stock only by what changed).
function NewInvoiceModal({ products, stockPoints, revising, defaultStockPoint, onClose, onCreate }) {
  // No default customer: pre-selecting the first name made it easy to
  // bill the wrong person.
  const [party, setParty] = useState(revising?.party ?? null);
  // a new sale starts at the store in view (sidebar store switcher), else the first shop
  const [stockPoint, setStockPoint] = useState(revising?.stock_point
    ?? stockPoints.find((s) => s.id === defaultStockPoint)?.id ?? stockPoints.find((s) => s.kind === "shop")?.id);
  // a revision starts from the invoice's lines, keeping the serial numbers already on them
  const [lines, setLines] = useState(() => (revising
    ? revisionLines(revising, products).map((l, i) => ({ ...blankLine(), ...l, serials: revising.items.filter((item) => !item.is_discount)[i]?.serial_numbers || [] }))
    : [blankLine()]));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [discount, setDiscount] = useState(() => (Number(revising?.discount_percent) ? String(Number(revising.discount_percent)) : ""));
  const [discountReason, setDiscountReason] = useState(revising?.discount_reason || "");

  // a revised invoice's own stock point may since have been made inactive
  const pointOptions = revising && !stockPoints.some((s) => s.id === revising.stock_point)
    ? [...stockPoints, { id: revising.stock_point, name: revising.stock_point_name }]
    : stockPoints;
  const shopSlug = pointOptions.find((s) => s.id === stockPoint)?.slug;
  const variantOf = (line) => products.find((p) => p.id === +line.productId)?.variants.find((v) => v.id === +line.variantId);
  // when revising at the same shop, the units already on this invoice are available to it too
  const inStock = (variant) => (variant?.stock?.find((s) => s.stock_point === shopSlug)?.quantity ?? 0)
    + (variant ? unitsOnInvoice(revising, variant.id, stockPoint) : 0);
  const setLine = (i, patch) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  // The same item can't be on two lines: choosing it again raises the quantity of the line it is already on.
  const place = (i, patch) => {
    const { lines: next, merged } = placeVariant(lines, i, patch);
    setLines(next);
    if (merged) {
      const p = products.find((x) => x.id === +next[merged.index].productId);
      const v = p?.variants.find((x) => x.id === +next[merged.index].variantId);
      setNote(`${p?.display_name || "This item"}${v?.spec ? ` (${v.spec})` : ""} is already on the invoice — quantity raised to ${merged.qty}.`);
    } else {
      setNote("");
    }
  };
  const pickProduct = (i, productId) => {
    const product = products.find((p) => p.id === +productId);
    const v = variantForProduct(product, lines, i);
    place(i, { productId, variantId: v ? String(v.id) : "", price: v ? String(v.sell_price) : "" });
  };
  // from the search box: a product, a SKU (that variant) or a serial number (that exact unit)
  const pickFromSearch = (i, { productId, variantId, serial }) => {
    if (!variantId) return pickProduct(i, productId);
    const v = products.find((p) => p.id === +productId)?.variants.find((x) => x.id === +variantId);
    const { lines: next, merged } = placeVariant(lines, i, { productId, variantId, price: v ? String(v.sell_price) : "" });
    const at = merged ? merged.index : i;
    if (serial && !next[at].serials.includes(serial)) {
      const serials = [...next[at].serials, serial];
      next[at] = { ...next[at], serials, qty: merged ? next[at].qty : Math.max(+next[at].qty || 1, serials.length) };
    }
    setLines(next);
    setNote(merged ? `${products.find((p) => p.id === +productId)?.display_name || "This item"}${v?.spec ? ` (${v.spec})` : ""} is already on the invoice — quantity raised to ${merged.qty}.` : "");
  };
  const pickVariant = (i, variantId) => {
    const v = products.find((p) => p.id === +lines[i].productId)?.variants.find((x) => x.id === +variantId);
    place(i, { variantId, price: v ? String(v.sell_price) : "" });
  };
  const subtotal = lines.reduce((sum, l) => sum + (+l.price || 0) * (+l.qty || 0), 0);
  const discountValue = discountOff(subtotal, discount);
  const total = subtotal - discountValue;

  const submit = async () => {
    setError("");
    if (+discount > 100) return setError("A discount can't be more than 100%.");
    if (+discount > 0 && !discountReason.trim()) return setError("Give a reason for the discount.");
    if (!party) return setError("Pick or add the customer.");
    const filled = lines.filter((l) => l.variantId);
    if (!filled.length) return setError("Add at least one product.");
    for (const l of filled) {
      const v = variantOf(l);
      if (!(+l.qty >= 1)) return setError("Every line needs a quantity of at least 1.");
      if (l.price === "" || +l.price < 0) return setError(`Enter a price for ${v?.spec || "each line"}.`);
      if (l.serialInfo?.tracked) {
        const need = Math.max(0, +l.qty - l.serialInfo.untracked);
        if (l.serials.length < need) return setError(`Pick the serial number of each unit of ${v?.spec || "this item"} (${l.serials.length} of ${need}).`);
        if (l.serials.length > +l.qty) return setError(`More serial numbers than units for ${v?.spec || "this item"}.`);
      }
    }
    setBusy(true);
    try {
      const items = filled.map((l) => ({
        variant: +l.variantId, qty: +l.qty, price: +l.price, remarks: (l.remarks || "").trim(),
        warranty_months: l.warranty ? +l.warranty : null, ...(l.serials.length ? { serials: l.serials } : {}),
      }));
      // a revision keeps its invoice date; only the customer, shop and lines change
      const offer = { discount_percent: +discount || 0, discount_reason: +discount > 0 ? discountReason.trim() : "" };
      await onCreate(revising ? { party, stock_point: stockPoint, items, ...offer } : { party, stock_point: stockPoint, date: todayISO(), items, ...offer });
    } catch (e) {
      const body = e.body || {};
      setError([].concat(body.items || body.discount_percent || body.discount_reason || body.detail || e.message).join(" · "));
    } finally {
      setBusy(false);
    }
  };

  const field = { fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, background: C.slip };
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip }}>
        <div className="flex items-center justify-between"><span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>{revising ? `Revise ${revising.code}` : "New sale invoice"}</span><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button></div>

        <div className="mt-4 space-y-3">
          <div className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            <span className="mb-1 block">Customer</span>
            <PartyPicker value={party} onChange={setParty} />
          </div>
          <label className="text-xs" style={{ display: "block", fontFamily: F.body, color: C.inkSoft }}>Sold through (stock is taken from here)
            <select value={stockPoint} onChange={(e) => { setStockPoint(+e.target.value); setLines((ls) => ls.map((l) => ({ ...l, serials: [], serialInfo: null }))); }} className="mt-1 w-full py-2 text-sm outline-none" style={field}>
              {pointOptions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
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
                  <div key={i}>
                  {/* minmax(0, …): a long product name must not widen its column and squeeze the others.
                      Phones: product on its own row, then variant / qty / price. */}
                  <div className="grid grid-cols-[minmax(0,1fr)_56px_88px_24px] items-start gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_64px_100px_24px]">
                    <ProductSearch products={products} productId={l.productId} stockPointId={stockPoint} onPick={(pick) => pickFromSearch(i, pick)} />
                    <div className="min-w-0">
                      <select value={l.variantId} onChange={(e) => pickVariant(i, e.target.value)} disabled={!product} title={v?.spec || "Variant"} className="w-full min-w-0 truncate py-1.5 text-sm outline-none" style={field}>
                        {product?.variants.map((x) => <option key={x.id} value={x.id}>{x.spec}</option>)}
                      </select>
                      {v && <span className="block whitespace-nowrap text-[11px]" style={{ fontFamily: F.mono, color: short ? C.carbon : C.inkSoft }}>{have} {revising ? "available" : "in stock"} here</span>}
                    </div>
                    <input type="number" min={1} value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} title="Quantity" className="w-full min-w-0 py-1.5 text-center text-sm outline-none" style={{ ...field, fontFamily: F.mono, borderColor: short ? C.carbon : C.rule }} />
                    <input value={l.price} onChange={(e) => setLine(i, { price: e.target.value.replace(/\D/g, "") })} placeholder="₹ each" title="Unit price -- edit for a discount" className="w-full min-w-0 py-1.5 text-right text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
                    <button type="button" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} className="pt-2" title="Remove line"><X size={14} style={{ color: C.inkSoft }} /></button>
                  </div>
                  {v && (
                    <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_170px]">
                      <input value={l.remarks} maxLength={300} onChange={(e) => setLine(i, { remarks: e.target.value })} placeholder="Remarks (optional), e.g. charger & bag included, minor scratch on lid"
                        aria-label="Remarks" className="w-full min-w-0 px-2 py-1.5 text-xs outline-none" style={field} />
                      <select value={l.warranty} onChange={(e) => setLine(i, { warranty: e.target.value })} aria-label="Warranty" title="Leave as No warranty if no guarantee is promised"
                        className="w-full py-1.5 text-xs outline-none" style={{ ...field, color: l.warranty ? C.ink : C.inkSoft, fontWeight: l.warranty ? 600 : 400 }}>
                        <option value="">No warranty</option>
                        {WARRANTY_CHOICES.map((m) => <option key={m} value={m}>Warranty: {warrantyLabel(m)}</option>)}
                      </select>
                    </div>
                  )}
                  {product?.serial_tracking && v && (
                    <SerialPicker variantId={v.id} stockPointId={stockPoint} qty={l.qty} value={l.serials}
                      onChange={(serials) => setLine(i, { serials, qty: Math.max(+l.qty || 0, serials.length) })}
                      onInfo={(serialInfo) => setLine(i, { serialInfo })} />
                  )}
                  </div>
                );
              })}
            </div>
            {note && <p role="status" className="mt-2 text-[11px]" style={{ fontFamily: F.body, color: C.stamp, fontWeight: 600 }}>{note}</p>}
            <button type="button" onClick={() => { setNote(""); setLines((ls) => [...ls, blankLine()]); }} className="mt-2 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}><Plus size={12} /> Add another item</button>
            <p className="mt-1 text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>The unit price starts at the list price.</p>
          </div>

          <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Discount %
              <input value={discount} inputMode="decimal" onChange={(e) => setDiscount(e.target.value.replace(/[^\d.]/g, ""))} placeholder="0"
                className="mt-1 w-full px-3 py-2 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
            </label>
            <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Reason{+discount > 0 ? "" : " (if discounted)"}
              <input value={discountReason} maxLength={200} disabled={!(+discount > 0)} onChange={(e) => setDiscountReason(e.target.value)} placeholder="e.g. Regular customer"
                className="mt-1 w-full px-3 py-2 text-sm outline-none disabled:opacity-60" style={field} />
            </label>
          </div>

          {discountValue > 0 && (
            <div className="space-y-1 px-3 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
              <div className="flex justify-between"><span style={{ fontFamily: F.body }}>Subtotal</span><span>{money(subtotal)}</span></div>
              <div className="flex justify-between" style={{ color: C.green }}><span style={{ fontFamily: F.body }}>Discount ({Number(discount)}%)</span><span>-{money(discountValue)}</span></div>
            </div>
          )}

          <div className="flex items-center justify-between px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
            <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total</span>
            <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(total)}</span>
          </div>
        </div>

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-5 flex w-full items-center justify-center gap-2 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          {revising ? <><Check size={13} /> {busy ? "Saving…" : "Save revised invoice"}</> : <><Plus size={13} /> {busy ? "Creating…" : "Generate invoice"}</>}
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
    <div className="mt-4 p-3" data-panel style={{ border: `1px solid ${C.green}66`, backgroundColor: `${C.green}10`, boxShadow: "none" }}>
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
  const balance = invoice.balance_due ?? invoice.total;
  const [amount, setAmount] = useState(String(balance));
  const [method, setMethod] = useState("UPI");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(todayISO());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    if (method !== "Cash" && !reference.trim()) return setError(`Enter the ${REFERENCE_HINT[method]} so this payment can be traced.`);
    const rupees = Number(amount);
    if (!Number.isInteger(rupees) || rupees <= 0 || rupees > balance) return setError(`Enter a whole amount from ₹1 to ${money(balance)}.`);
    setBusy(true);
    try {
      await onSettle(invoice.id, { pay_method: method, payment_reference: reference.trim(), paid_on: paidOn, ...(rupees < balance ? { amount: rupees } : {}) });
      setReference("");
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
      {invoice.part_payments?.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          {invoice.part_payments.map((p) => <li key={p.id}>Part paid <b style={{ color: C.ink }}>{money(p.amount)}</b> via {p.pay_method} on {fmt(p.paid_on)}{p.payment_reference ? ` · ref ${p.payment_reference}` : ""}</li>)}
          <li style={{ color: C.carbon, fontWeight: 600 }}>Still owed {money(balance)}</li>
        </ul>
      )}
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block text-xs sm:col-span-2" style={{ fontFamily: F.body, color: C.inkSoft }}>Amount received (₹) — less than {money(balance)} records a part payment
          <input type="number" inputMode="numeric" min="1" max={balance} step="1" value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
        <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Method
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field}>
            {PAYMENT_METHODS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Paid on
          <input type="date" value={paidOn} max={todayISO()} onChange={(e) => setPaidOn(e.target.value)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
        <label className="block text-xs sm:col-span-2" style={{ fontFamily: F.body, color: C.inkSoft }}>{REFERENCE_HINT[method]}
          <input value={reference} maxLength={80} onChange={(e) => setReference(e.target.value)} placeholder={method === "Cash" ? "Optional" : "Required"} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
        </label>
      </div>
      <ErrorNote message={error} />
      <button onClick={submit} disabled={busy} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
        <Check size={12} /> {busy ? "Saving…" : Number(amount) < balance ? `Record part payment — ${money(Number(amount) || 0)}` : `Mark paid — ${money(balance)}`}
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
  const [picked, setPicked] = useState({}); // item id -> serial numbers coming back
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
  const returnable = invoice.items.filter((it) => !it.is_discount && it.qty - (it.returned_qty || 0) > 0);
  const returnedValue = invoice.items.reduce((sum, it) => sum + (Number(qty[it.id]) || 0) * it.price, 0);
  // a return gives back what was paid: the price less the invoice's discount
  const value = isSale ? Math.min(left, returnedValue - discountOff(returnedValue, invoice.discount_percent)) : Number(amount) || 0;
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
        body.items = Object.entries(qty).filter(([, q]) => Number(q) > 0).map(([item, q]) => ({ item: Number(item), qty: Number(q), serials: picked[item] || [] }));
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
              <div key={it.id} className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                <div className="flex items-center justify-between gap-2">
                  <span>{it.product_name} <span style={{ fontFamily: F.mono, color: C.inkSoft }}>· {money(it.price)} each{Number(invoice.discount_percent) > 0 ? ` less ${Number(invoice.discount_percent)}%` : ""} · {max} returnable</span></span>
                  <input type="number" min={0} max={max} value={qty[it.id] ?? ""} placeholder="0" title="Quantity returned"
                    onChange={(e) => setQty({ ...qty, [it.id]: Math.max(0, Math.min(max, Number(e.target.value.replace(/\D/g, "")) || 0)) })}
                    className="w-16 px-2 py-1 text-right text-sm outline-none" style={{ ...field, fontFamily: F.mono }} />
                </div>
                {it.sold_serials?.length > 0 && (
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span style={{ color: C.inkSoft }}>Which unit{max > 1 ? "s" : ""}?</span>
                    {it.sold_serials.map((sn) => {
                      const on = (picked[it.id] || []).includes(sn);
                      return (
                        <button key={sn} type="button" role="checkbox" aria-checked={on} className="rounded px-1.5 py-0.5 text-[11px]"
                          onClick={() => {
                            const next = on ? (picked[it.id] || []).filter((x) => x !== sn) : [...(picked[it.id] || []), sn];
                            setPicked({ ...picked, [it.id]: next });
                            setQty({ ...qty, [it.id]: Math.min(max, Math.max(next.length, on ? next.length : Number(qty[it.id]) || 0)) });
                          }}
                          style={{ fontFamily: F.mono, fontWeight: 700, border: `1px solid ${on ? C.carbon : C.rule}`, backgroundColor: on ? C.carbon : "transparent", color: on ? C.onAccent : C.ink }}>{sn}</button>
                      );
                    })}
                  </div>
                )}
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

function InvoiceDetail({ invoice, onClose, onSettle, onChanged, onRevise }) {
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
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{invoice.code}</p>
            <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{invoice.party_name} · {fmt(invoice.date)} · {invoice.stock_point_name}</p>
            {invoice.reference && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.ink }}>{invoice.source_label}: {invoice.reference}</p>}
          </div>
          <div className="flex items-center gap-2">
            {canRevise(invoice, can) && (
              <button onClick={() => onRevise(invoice)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, fontWeight: 600, color: C.ink }}>
                <PencilLine size={12} /> Revise
              </button>
            )}
            <button onClick={() => setPrinting(true)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, fontWeight: 600, color: C.ink }}>
              <Printer size={12} /> Print
            </button>
            <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
          </div>
        </div>

        <div className="mt-4 space-y-1.5">
          {invoice.items.map((it) => (
            <div key={it.id} className="flex items-center justify-between px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
              <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{it.product_name} <span style={{ fontFamily: F.mono, color: C.inkSoft, fontSize: 11 }}>{it.qty} × {money(it.price)}</span>{it.serial_numbers?.length > 0 && <span className="block text-[11px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>S/N {it.serial_numbers.join(", ")}</span>}{it.remarks && <span className="block text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>Remarks: {it.remarks}</span>}{it.warranty_months > 0 && <span className="block text-[11px]" style={{ fontFamily: F.body, color: C.green, fontWeight: 600 }}>Warranty: {warrantyLabel(it.warranty_months)}</span>}</span>
              <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(it.price * it.qty)}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between px-3 py-2" data-panel style={{ boxShadow: "none" }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(invoice.total)}</span>
        </div>
        {invoice.discount_amount > 0 && (
          <p className="mt-1 px-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            {Number(invoice.discount_percent)}% discount ({money(invoice.discount_amount)}) by {invoice.discount_by_name || "staff"}: {invoice.discount_reason}
          </p>
        )}
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
        ) : can("invoices.settle") && <RecordPayment key={invoice.balance_due} invoice={invoice} onSettle={onSettle} />}
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
  { id: "onsite", label: "On-site" },
];
const SOURCE_COLOR = { sale: C.stamp, repair: C.amber, rental: C.blue, onsite: C.green };

/*
 * Every invoice the business raises -- product sales, repair jobs and
 * rental rent -- is listed and paid here. Repairs and Rentals raise
 * their invoices from their own screens; payment is only ever taken
 * on this screen.
 */
export default function Invoices() {
  const { can, me } = useSession();
  const [invoices, setInvoices] = useState(null);
  const [products, setProducts] = useState([]);
  const [stockPoints, setStockPoints] = useState([]);
  const [error, setError] = useState("");
  const [source, setSource] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [order, setOrder] = useOrder("invoices", "desc");
  const [adding, setAdding] = useState(false);
  const [revising, setRevising] = useState(null);
  const [openInvoice, setOpenInvoice] = useState(null);
  // Arriving from a customer's Pay button: /sales?party=<id>&due=1 shows just their unpaid invoices.
  const [partyFilter, setPartyFilter] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("party") ? { id: Number(params.get("party")), due: params.get("due") === "1" } : null;
  });
  const clearPartyFilter = () => {
    setPartyFilter(null);
    window.history.replaceState(window.history.state, "", "/sales");
  };
  const autoOpened = useRef(false);
  useEffect(() => {
    // one unpaid invoice: open it straight away, ready for the payment
    if (autoOpened.current || !partyFilter?.due || !invoices) return;
    autoOpened.current = true;
    const due = invoices.filter((inv) => inv.party === partyFilter.id && isOutstanding(inv));
    if (due.length === 1) setOpenInvoice(due[0]);
  }, [invoices, partyFilter]);

  // Only products that have something sellable: stock and prices live
  // on variants, so a product with none yet can't go on an invoice.
  // Reloaded after every sale, cancellation or return, so the new-sale
  // form's "in stock here" counts are the server's, never stale.
  const loadProducts = () => api.getAll("/products/").then((all) => setProducts(all.filter((p) => p.variants.length))).catch(() => {});

  useEffect(() => {
    api.getAll("/invoices/").then(setInvoices).catch((e) => setError(e.message));
    loadProducts();
    api.get("/stock-points/?active=1").then((d) => setStockPoints(d.results ?? d));
  }, []);

  // a store was edited: invoices show its name, the new-invoice form lists it
  useEffect(() => onStoreChanged(() => {
    api.getAll("/invoices/").then(setInvoices).catch(() => {});
    api.get("/stock-points/?active=1").then((d) => setStockPoints(d.results ?? d)).catch(() => {});
  }), []);

  const create = async (payload) => {
    const inv = await api.post("/invoices/", payload);
    setInvoices((l) => [inv, ...l]);
    setAdding(false);
    loadProducts();
    toast.success(`Sale ${inv.code} created`, `₹${Number(inv.total || 0).toLocaleString("en-IN")}${inv.party_name ? ` · ${inv.party_name}` : ""} · ${inv.status === "Paid" ? "Paid" : "Payment pending"}.`);
  };

  // same invoice, same number: the server swaps its lines and moves stock by the difference
  const revise = async (payload) => {
    invoiceChanged(await api.patch(`/invoices/${revising.id}/`, payload));
    setRevising(null);
  };

  // cancelling or refunding a sale puts its units back on the shelf
  const invoiceChanged = (inv) => {
    replaceInvoice(inv);
    if (inv.source === "sale") loadProducts();
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
  const forParty = partyFilter
    ? invoices.filter((inv) => inv.party === partyFilter.id && (!partyFilter.due || isOutstanding(inv)))
    : invoices;
  const bySource = source === "all" ? forParty : forParty.filter((inv) => inv.source === source);
  const filteredPartyName = partyFilter && invoices.find((inv) => inv.party === partyFilter.id)?.party_name;
  const byStatus = statusFilter === "all" ? bySource : bySource.filter((inv) => inv.status === statusFilter);
  const visibleInvoices = q
    ? byStatus.filter((inv) => inv.code.toLowerCase().includes(q) || inv.party_name.toLowerCase().includes(q) || (inv.reference || "").toLowerCase().includes(q))
    : byStatus;
  const awaiting = bySource.filter(isOutstanding);
  const count = (id) => (id === "all" ? invoices.length : invoices.filter((inv) => inv.source === id).length);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="px-5 pt-6 sm:px-8">
        <PageHeader
          title="Sales & Invoices"
          subtitle="Every invoice — sales, repairs and rentals — and every payment, in one place"
          actions={can("invoices.create") && <PillButton icon={Plus} primary onClick={() => setAdding(true)}>New sale invoice</PillButton>}
        />
      </div>
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
        <div className="flex min-w-0 max-w-full flex-col gap-2">
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
      </header>

      <div className="flex flex-wrap items-center gap-3 px-5 pb-4 sm:px-8">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by invoice code, customer, ticket or agreement" className="basis-full sm:basis-0" />
        <OrderToggle value={order} onChange={setOrder} label="Invoice order" />
        <span className="text-xs" aria-live="polite" style={{ fontFamily: F.body, color: C.inkSoft }}>
          To collect: <b style={{ fontFamily: F.mono, color: C.ink }}>{money(awaiting.reduce((sum, inv) => sum + (inv.balance_due ?? inv.total), 0))}</b> across {awaiting.length} invoice{awaiting.length !== 1 ? "s" : ""}
        </span>
      </div>

      {partyFilter && (
        <div className="mx-5 mb-3 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-xs sm:mx-8" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.green}`, backgroundColor: `${C.green}0D` }}>
          Showing {partyFilter.due ? "unpaid invoices" : "invoices"} for <b>{filteredPartyName || "this customer"}</b>. Open one to record a full or part payment.
          <button type="button" onClick={clearPartyFilter} className="ml-auto flex items-center gap-1 underline" style={{ color: C.inkSoft }}><X size={12} /> Show all invoices</button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-5 pb-4 sm:px-8">
        <div className="flex flex-col gap-2.5">
          {orderRows(visibleInvoices, order, "desc").map((inv) => (
            <div
              key={inv.id}
              data-listcard
              role="button"
              tabIndex={0}
              aria-label={`Open invoice ${inv.code}`}
              onClick={() => setOpenInvoice(inv)}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  setOpenInvoice(inv);
                }
              }}
              className="flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5 sm:px-5"
            >
              <div className="min-w-[140px] flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{inv.code}</span>
                  <Pill color={SOURCE_COLOR[inv.source]}>{inv.source_label}</Pill>
                  {inv.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{inv.recurring_interval}</Pill>}
                </div>
                <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  {inv.party_name}{inv.party_type ? ` (${inv.party_type})` : ""} · {fmt(inv.date)}{inv.reference ? ` · ${inv.reference}` : ""}
                </p>
              </div>
              <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.stock_point_name}</span>
              <span className="text-sm sm:min-w-24 sm:text-right" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(inv.total)}</span>
              <Pill color={STATUS_COLOR[inv.status]}>{invoiceStatusLabel(inv)}</Pill>
              {canRevise(inv, can) && (
                <button type="button" onClick={(e) => { e.stopPropagation(); setRevising(inv); }} className="flex items-center gap-1 rounded-full px-3 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body, fontWeight: 700 }}>
                  <PencilLine size={11} /> Revise
                </button>
              )}
              {isOutstanding(inv) && can("invoices.settle") && (
                <button type="button" onClick={(e) => { e.stopPropagation(); setOpenInvoice(inv); }} className="flex items-center gap-1 rounded-full px-3 py-1.5 text-xs" style={{ border: `1px solid ${C.green}66`, backgroundColor: `${C.green}0D`, color: C.green, fontFamily: F.body, fontWeight: 700 }}>
                  <IndianRupee size={11} /> Record payment
                </button>
              )}
            </div>
          ))}
          {!visibleInvoices.length && (
            <p className="rounded-2xl px-4 py-12 text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft, border: `1px dashed ${C.ruleStrong}` }}>
              {invoices.length ? "No invoices match these filters." : "No invoices yet."}
            </p>
          )}
        </div>
      </div>

      {adding && <NewInvoiceModal products={products} stockPoints={stockPoints} defaultStockPoint={me?.active_store} onClose={() => setAdding(false)} onCreate={create} />}
      {/* lines are matched to products, so wait for them */}
      {revising && products.length > 0 && <NewInvoiceModal key={revising.id} products={products} stockPoints={stockPoints} revising={revising} onClose={() => setRevising(null)} onCreate={revise} />}
      {openInvoice && <InvoiceDetail invoice={openInvoice} onClose={() => setOpenInvoice(null)} onSettle={settle} onChanged={invoiceChanged} onRevise={(inv) => { setOpenInvoice(null); setRevising(inv); }} />}
    </div>
  );
}
