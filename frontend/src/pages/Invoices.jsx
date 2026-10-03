import { useEffect, useState } from "react";
import { Check, IndianRupee, Mail, Plus, Printer, Repeat2, ShieldCheck, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, PillButton, SearchInput, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import PrintableInvoice from "../components/invoices/PrintableInvoice";
import UpiPaymentLink from "../components/invoices/UpiPaymentLink";

const STATUS_COLOR = { Paid: "#36D399", "Payment link sent": "#F5A623", Overdue: "#FB5B5B" };
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

function NewInvoiceModal({ parties, products, stockPoints, onClose, onCreate }) {
  const [party, setParty] = useState(parties[0]?.id);
  const [stockPoint, setStockPoint] = useState(stockPoints.find((s) => s.kind === "shop")?.id);
  const [productId, setProductId] = useState(products[0]?.id);
  const [vcode, setVcode] = useState(products[0]?.variants[0]?.code);
  const [qty, setQty] = useState(1);
  const [recurring, setRecurring] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const product = products.find((p) => p.id === productId);
  const variant = product?.variants.find((v) => v.code === vcode) || product?.variants[0];

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (!variant) throw new Error("Pick a product to invoice.");
      await onCreate({
        party, stock_point: stockPoint, date: new Date().toISOString().slice(0, 10),
        items: [{ variant: variant.id, qty, price: variant.sell_price }],
        recurring_interval: recurring,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-lg p-6" data-panel style={{ backgroundColor: C.slip, border: `2px solid ${C.ruleStrong || C.rule}`, boxShadow: "0 10px 30px rgba(0,0,0,0.5)" }}>
        <div className="flex items-center justify-between"><span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>New invoice</span><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>

        <div className="mt-4 space-y-3">
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Party
            <select value={party} onChange={(e) => setParty(+e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {parties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Sold through
            <select value={stockPoint} onChange={(e) => setStockPoint(+e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Product
            <select value={productId} onChange={(e) => { const pid = +e.target.value; setProductId(pid); setVcode(products.find((p) => p.id === pid)?.variants[0]?.code); }} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {products.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
            </select>
          </label>
          <div className="flex gap-3">
            <label className="block flex-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Variant
              <select value={vcode} onChange={(e) => setVcode(e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
                {product?.variants.map((v) => <option key={v.code} value={v.code}>{v.spec} — {money(v.sell_price)}</option>)}
              </select>
            </label>
            <label className="block w-20 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Qty
              <input type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, +e.target.value))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
            </label>
          </div>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Recurring billing
            <select value={recurring} onChange={(e) => setRecurring(e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              <option value="">One-time only</option>
              <option value="weekly">Repeat weekly</option>
              <option value="monthly">Repeat monthly</option>
              <option value="6-month">Repeat every 6 months</option>
            </select>
          </label>
          {variant && (
            <div className="flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Amount</span>
              <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(variant.sell_price * qty)}</span>
            </div>
          )}
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
        <div className="mt-2 flex items-center gap-2">
          <Pill color={STATUS_COLOR[invoice.status]}>{invoiceStatusLabel(invoice)}</Pill>
        </div>
        {invoice.status === "Paid" ? (
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
        <UpiPaymentLink invoice={invoice} onChanged={onChanged} />

        {warranty === undefined ? <div className="mt-4"><Spinner /></div> : <WarrantyCard invoice={invoice} warranty={warranty} onGranted={setWarranty} />}
      </div>
      {printing && <PrintableInvoice invoiceId={invoice.id} onClose={() => setPrinting(false)} />}
    </div>
  );
}

export default function Invoices() {
  const { can } = useSession();
  const [invoices, setInvoices] = useState(null);
  // Repair bills need repairs.view (Sales Staff don't hold it) -- those
  // roles just don't get the Repairs tab instead of the page failing.
  const canRepairs = can("repairs.view");
  const [repairInvoices, setRepairInvoices] = useState(canRepairs ? null : []);
  const [parties, setParties] = useState([]);
  const [products, setProducts] = useState([]);
  const [stockPoints, setStockPoints] = useState([]);
  const [error, setError] = useState("");
  const [source, setSource] = useState("sales"); // "sales" | "repairs"
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [openInvoice, setOpenInvoice] = useState(null);

  const loadInvoices = (status) => api.get(`/invoices/${status !== "all" ? `?status=${encodeURIComponent(status)}` : ""}`).then((d) => setInvoices(d.results ?? d)).catch((e) => setError(e.message));

  useEffect(() => {
    loadInvoices("all");
    api.getAll("/parties/").then(setParties);
    // Only products that have something sellable: stock and prices live
    // on variants, so a product with none yet can't go on an invoice.
    api.getAll("/products/").then((all) => setProducts(all.filter((p) => p.variants.length)));
    api.get("/stock-points/").then((d) => setStockPoints(d.results ?? d));
  }, []);

  useEffect(() => {
    if (canRepairs) api.get("/repair-invoices/").then((d) => setRepairInvoices(d.results ?? d)).catch((e) => setError(e.message));
  }, [canRepairs]);

  useEffect(() => { loadInvoices(statusFilter); }, [statusFilter]);

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
  if (!invoices || !repairInvoices) return <Spinner label="Loading invoices…" />;

  const totalRepairRevenue = repairInvoices.filter((r) => r.status === "Paid").reduce((s, r) => s + r.amount, 0);

  // Client-side only -- both lists are already fully loaded for this
  // view (status filtering for sales still goes through the API), so
  // filtering by code/party here needs no extra round trip.
  const q = query.trim().toLowerCase();
  const visibleInvoices = q ? invoices.filter((inv) => inv.code.toLowerCase().includes(q) || inv.party_name.toLowerCase().includes(q)) : invoices;
  const visibleRepairInvoices = q ? repairInvoices.filter((r) => r.code.toLowerCase().includes(q) || r.party_name.toLowerCase().includes(q)) : repairInvoices;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="px-5 pt-6 sm:px-8">
        <PageHeader title="Sales & Invoices" subtitle="Sales and repair billing, in one place" />
      </div>
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
        <div className="flex flex-col gap-2">
          <TabBar
            tabs={[
              { id: "sales", label: `Sales (${invoices.length})` },
              ...(canRepairs ? [{ id: "repairs", label: `Repairs (${repairInvoices.length})` }] : []),
            ]}
            value={source}
            onChange={setSource}
          />
          {source === "sales" && (
            <div className="overflow-x-auto">
              <TabBar
                tabs={["all", "Paid", "Payment link sent", "Overdue"].map((s) => ({ id: s, label: s === "all" ? "All invoices" : statusLabel(s) }))}
                value={statusFilter}
                onChange={setStatusFilter}
              />
            </div>
          )}
        </div>
        {source === "sales" && can("invoices.create") && (
          <PillButton icon={Plus} primary onClick={() => setAdding(true)}>New invoice</PillButton>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-3 px-5 pb-4 sm:px-8">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder={source === "sales" ? "Search by invoice code or customer" : "Search by bill code or customer"} />
      </div>

      {source === "repairs" && (
        <div className="mx-5 mb-3 flex items-center justify-between px-3 py-2 sm:mx-8" style={{ backgroundColor: C.slip2 }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Repair revenue, settled</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(totalRepairRevenue)}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-5 pb-4 sm:px-8">
        {source === "sales" ? (
          <div className="flex flex-col gap-2.5">
            {visibleInvoices.map((inv) => (
              <div key={inv.id} data-listcard onClick={() => setOpenInvoice(inv)} className="flex flex-wrap items-center gap-3 px-5 py-3.5 cursor-pointer">
                <div className="min-w-[140px] flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{inv.code}</span>
                    {inv.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{inv.recurring_interval}</Pill>}
                  </div>
                  <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.party_name} · {fmt(inv.date)}</p>
                </div>
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.stock_point_name}</span>
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink, minWidth: 96, textAlign: "right" }}>{money(inv.total)}</span>
                <Pill color={STATUS_COLOR[inv.status]}>{invoiceStatusLabel(inv)}</Pill>
                {inv.status !== "Paid" && can("invoices.settle") && (
                  <button onClick={(e) => { e.stopPropagation(); setOpenInvoice(inv); }} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
                    <IndianRupee size={11} /> Record payment
                  </button>
                )}
              </div>
            ))}
            {!visibleInvoices.length && (
              <p className="px-3 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
                {invoices.length ? "No invoices match that search." : "No invoices in this view."}
              </p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {visibleRepairInvoices.map((r) => (
              <div key={r.id} data-listcard className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <div className="min-w-[140px] flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{r.code}</span>
                    {r.is_followup && <Pill color={C.amber}>follow-up</Pill>}
                  </div>
                  <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{r.party_name} · {fmt(r.date)} · ticket {r.ticket_code}</p>
                </div>
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{r.stock_point_name}</span>
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink, minWidth: 96, textAlign: "right" }}>{money(r.amount)}</span>
                <Pill color={STATUS_COLOR[r.status] || C.green}>{r.status}</Pill>
              </div>
            ))}
            {!visibleRepairInvoices.length && (
              <p className="px-3 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
                {repairInvoices.length ? "No repair bills match that search." : "No repair bills yet -- these appear automatically when a repair ticket is settled."}
              </p>
            )}
          </div>
        )}
      </div>

      {adding && <NewInvoiceModal parties={parties} products={products} stockPoints={stockPoints} onClose={() => setAdding(false)} onCreate={create} />}
      {openInvoice && <InvoiceDetail invoice={openInvoice} onClose={() => setOpenInvoice(null)} onSettle={settle} onChanged={replaceInvoice} />}
    </div>
  );
}
