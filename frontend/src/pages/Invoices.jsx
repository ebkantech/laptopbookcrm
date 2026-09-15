import { useEffect, useState } from "react";
import { Check, Link2, Mail, Plus, Repeat2, ShieldCheck, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, Spinner } from "../components/Atoms";

const STATUS_COLOR = { Paid: "#36D399", "Payment link sent": "#F5A623", Overdue: "#FB5B5B" };
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
      await onCreate({
        party, stock_point: stockPoint, date: new Date().toISOString().slice(0, 10),
        items: [{ variant: variant.id, qty, price: variant.sell_price }],
        recurring_interval: recurring, pay_method: "Razorpay link",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-lg p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
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
            <select value={productId} onChange={(e) => { const pid = +e.target.value; setProductId(pid); setVcode(products.find((p) => p.id === pid).variants[0].code); }} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
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
          <Link2 size={13} /> {busy ? "Creating…" : "Generate invoice + payment link"}
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
      <div className="mt-4 p-3" data-panel style={{ border: `1px dashed ${C.rule}` }}>
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
    <div className="mt-4 p-3" data-panel style={{ border: `1px solid ${C.green}`, backgroundColor: `${C.green}0A` }}>
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

function InvoiceDetail({ invoice, onClose, onSettle }) {
  const { can } = useSession();
  const [warranty, setWarranty] = useState(undefined); // undefined = loading, null = none

  useEffect(() => {
    api.get(`/warranties/?invoice=${invoice.id}`).then((d) => {
      const rows = d.results ?? d;
      setWarranty(rows[0] || null);
    });
  }, [invoice.id]);

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{invoice.code}</p>
            <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{invoice.party_name} · {fmt(invoice.date)} · {invoice.stock_point_name}</p>
          </div>
          <button onClick={onClose}><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-4 space-y-1.5">
          {invoice.items.map((it) => (
            <div key={it.id} className="flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{it.product_name} <span style={{ fontFamily: F.mono, color: C.inkSoft, fontSize: 11 }}>×{it.qty}</span></span>
              <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(it.price * it.qty)}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between px-3 py-2" data-panel style={{ border: `1px solid ${C.rule}` }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(invoice.total)}</span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <Pill color={STATUS_COLOR[invoice.status]}>{invoice.status}</Pill>
          {invoice.status !== "Paid" && can("invoices.settle") && (
            <button onClick={() => onSettle(invoice.id)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
              <Check size={11} /> Mark settled
            </button>
          )}
        </div>

        {warranty === undefined ? <div className="mt-4"><Spinner /></div> : <WarrantyCard invoice={invoice} warranty={warranty} onGranted={setWarranty} />}
      </div>
    </div>
  );
}

export default function Invoices() {
  const { can } = useSession();
  const [invoices, setInvoices] = useState(null);
  const [repairInvoices, setRepairInvoices] = useState(null);
  const [parties, setParties] = useState([]);
  const [products, setProducts] = useState([]);
  const [stockPoints, setStockPoints] = useState([]);
  const [error, setError] = useState("");
  const [source, setSource] = useState("sales"); // "sales" | "repairs"
  const [statusFilter, setStatusFilter] = useState("all");
  const [adding, setAdding] = useState(false);
  const [openInvoice, setOpenInvoice] = useState(null);

  const loadInvoices = (status) => api.get(`/invoices/${status !== "all" ? `?status=${encodeURIComponent(status)}` : ""}`).then((d) => setInvoices(d.results ?? d)).catch((e) => setError(e.message));

  useEffect(() => {
    loadInvoices("all");
    api.get("/repair-invoices/").then((d) => setRepairInvoices(d.results ?? d)).catch((e) => setError(e.message));
    api.get("/parties/").then((d) => setParties(d.results ?? d));
    api.get("/products/").then((d) => setProducts(d.results ?? d));
    api.get("/stock-points/").then((d) => setStockPoints(d.results ?? d));
  }, []);

  useEffect(() => { loadInvoices(statusFilter); }, [statusFilter]);

  const create = async (payload) => {
    const inv = await api.post("/invoices/", payload);
    setInvoices((l) => [inv, ...l]);
    setAdding(false);
  };

  const settle = async (id) => {
    const inv = await api.post(`/invoices/${id}/settle/`);
    setInvoices((l) => l.map((i) => (i.id === id ? inv : i)));
    setOpenInvoice((cur) => (cur?.id === id ? inv : cur));
  };

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!invoices || !repairInvoices) return <Spinner label="Loading invoices…" />;

  const totalRepairRevenue = repairInvoices.filter((r) => r.status === "Paid").reduce((s, r) => s + r.amount, 0);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8" style={{ borderBottom: `1px solid ${C.rule}` }}>
        <div className="flex flex-col gap-2">
          <div className="flex" style={{ border: `1px solid ${C.rule}` }}>
            <button onClick={() => setSource("sales")} className="px-3 py-1.5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: source === "sales" ? C.onAccent : C.inkSoft, backgroundColor: source === "sales" ? C.stamp : "transparent" }}>Sales ({invoices.length})</button>
            <button onClick={() => setSource("repairs")} className="px-3 py-1.5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: source === "repairs" ? C.onAccent : C.inkSoft, backgroundColor: source === "repairs" ? C.amber : "transparent" }}>Repairs ({repairInvoices.length})</button>
          </div>
          {source === "sales" && (
            <div className="flex gap-4 overflow-x-auto">
              {["all", "Paid", "Payment link sent", "Overdue"].map((s) => (
                <button key={s} onClick={() => setStatusFilter(s)} className="shrink-0 pb-1 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: statusFilter === s ? C.ink : C.inkSoft, borderBottom: `2px solid ${statusFilter === s ? C.orange : "transparent"}` }}>
                  {s === "all" ? "All invoices" : s}
                </button>
              ))}
            </div>
          )}
        </div>
        {source === "sales" && can("invoices.create") && (
          <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 px-3 py-2 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
            <Plus size={14} /> New invoice
          </button>
        )}
      </header>

      {source === "repairs" && (
        <div className="mx-5 mt-3 flex items-center justify-between px-3 py-2 sm:mx-8" style={{ backgroundColor: C.slip2 }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Repair revenue, settled</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(totalRepairRevenue)}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {source === "sales" ? (
          <>
            {invoices.map((inv) => (
              <div key={inv.id} data-row onClick={() => setOpenInvoice(inv)} className="flex flex-wrap items-center gap-3 px-5 py-3.5 sm:px-8 cursor-pointer" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <div className="min-w-[140px] flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{inv.code}</span>
                    {inv.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{inv.recurring_interval}</Pill>}
                  </div>
                  <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.party_name} · {fmt(inv.date)}</p>
                </div>
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{inv.stock_point_name}</span>
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink, minWidth: 96, textAlign: "right" }}>{money(inv.total)}</span>
                <Pill color={STATUS_COLOR[inv.status]}>{inv.status}</Pill>
                {inv.status !== "Paid" && can("invoices.settle") && (
                  <button onClick={(e) => { e.stopPropagation(); settle(inv.id); }} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
                    <Check size={11} /> Mark settled
                  </button>
                )}
              </div>
            ))}
            {!invoices.length && <p className="px-8 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No invoices in this view.</p>}
          </>
        ) : (
          <>
            {repairInvoices.map((r) => (
              <div key={r.id} data-row className="flex flex-wrap items-center gap-3 px-5 py-3.5 sm:px-8" style={{ borderBottom: `1px solid ${C.rule}` }}>
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
            {!repairInvoices.length && <p className="px-8 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No repair bills yet -- these appear automatically when a repair ticket is settled.</p>}
          </>
        )}
      </div>

      {adding && <NewInvoiceModal parties={parties} products={products} stockPoints={stockPoints} onClose={() => setAdding(false)} onCreate={create} />}
      {openInvoice && <InvoiceDetail invoice={openInvoice} onClose={() => setOpenInvoice(null)} onSettle={settle} />}
    </div>
  );
}
