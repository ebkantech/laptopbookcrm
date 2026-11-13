import { useEffect, useState } from "react";
import { ArrowRight, Award, ChevronRight, LineChart, Truck } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, compact, fmt, money } from "../../lib/theme";
import { ErrorNote, Spinner } from "../Atoms";
import { DetailFrame } from "./MetricDetail";

const KIND_LABEL = { products: "Product sales", parts: "Spare parts", service: "Service charges", rent: "Rent", discounts: "Discounts" };
const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`);
const tone = (n) => (n > 0 ? C.green : n < 0 ? C.carbon : C.ink);

/* The dashboard's date filter as a Profit & Loss period. */
function periodQuery({ dateFrom, dateTo }) {
  if (!dateFrom && !dateTo) return "period=this_month";
  const today = new Date().toISOString().slice(0, 10);
  const from = dateFrom || `${(dateTo || today).slice(0, 4)}-01-01`;
  return `period=custom&date_from=${from}&date_to=${dateTo || today}`;
}

/* The figures for what the dashboard is filtered to: one store, or the whole business. */
function pick(data, channel) {
  if (!data) return null;
  if (channel && channel !== "all") {
    const row = data.stores.find((s) => s.store.slug === channel);
    return row ? { ...row, label: row.store.name } : null;
  }
  if (data.consolidated) return { ...data.consolidated, label: "All stores" };
  return data.stores[0] ? { ...data.stores[0], label: data.stores[0].store.name } : null;
}

/*
 * First card on the dashboard, for those allowed to see Profit & Loss:
 * net profit (gross when expenses aren't recorded), with service income
 * kept apart from goods. Click for the full picture -- income by kind,
 * stores side by side and which supplier earns the business more.
 */
export default function ProfitLossCard({ filters, onGo }) {
  const [data, setData] = useState(null);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const qs = periodQuery(filters);

  useEffect(() => {
    setError("");
    api.get(`/reports/profit-loss/stores/?${qs}`).then(setData, (e) => (e.status === 403 ? setDenied(true) : setError(e.message)));
  }, [qs]);

  if (denied) return null;
  const st = pick(data, filters.channel);
  const known = st && st.net_profit !== null;
  const headline = st ? (known ? st.net_profit : st.gross_profit) : null;
  const kinds = Object.fromEntries((st?.by_kind || []).map((k) => [k.kind, k]));
  const goods = (kinds.products?.gross_profit || 0) + (kinds.parts?.gross_profit || 0);
  const service = kinds.service?.gross_profit || 0;
  const periodLabel = data ? (data.period.key === "this_month" ? "This month" : `${fmt(data.period.start)} – ${fmt(data.period.end)}`) : "";

  return (
    <>
      <button type="button" onClick={() => st && setOpen(true)} disabled={!st}
        className="group min-w-0 rounded-2xl p-3.5 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-lg sm:col-span-2 sm:p-5"
        style={{ background: `linear-gradient(135deg, ${C.slip} 0%, ${C.slip2} 100%)`, border: `1px solid color-mix(in srgb, ${C.stamp} 33%, transparent)`,
          boxShadow: "0 1px 2px rgba(35,40,31,0.04), 0 8px 24px -12px rgba(35,40,31,0.10)" }}
        aria-label="Profit and loss — open details">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.12em", color: C.inkSoft }}>
              Profit & Loss · {st?.label || "…"} · {periodLabel}
            </p>
            {error ? <p className="mt-2 text-xs" style={{ color: C.carbon }}>{error}</p> : !data ? <div className="mt-3"><Spinner label="Working out profit…" /></div> : !st ? (
              <p className="mt-3 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No figures for this store.</p>
            ) : (
              <>
                <p className="mt-2 text-2xl font-extrabold tracking-tight sm:text-[30px]" style={{ fontFamily: F.display, color: tone(headline) }}>
                  {compact(headline)}
                  <span className="ml-2 align-middle text-xs font-semibold" style={{ fontFamily: F.body, color: C.inkSoft }}>
                    {known ? "net profit" : "gross profit"} · margin {pct(known ? st.net_margin_pct : st.gross_margin_pct)}
                  </span>
                </p>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  <span>Revenue <b style={{ fontFamily: F.mono, color: C.ink }}>{compact(st.revenue)}</b></span>
                  <span>Goods profit <b style={{ fontFamily: F.mono, color: tone(goods) }}>{compact(goods)}</b></span>
                  <span>Service income <b style={{ fontFamily: F.mono, color: tone(service) }}>{compact(service)}</b></span>
                  {kinds.rent?.revenue ? <span>Rent <b style={{ fontFamily: F.mono, color: tone(kinds.rent.gross_profit) }}>{compact(kinds.rent.gross_profit)}</b></span> : null}
                  {known && <span>Expenses <b style={{ fontFamily: F.mono, color: C.ink }}>{compact(st.expenses)}</b></span>}
                </div>
                {!known && <p className="mt-1 text-[11px]" style={{ fontFamily: F.body, color: C.amber }}>No expenses recorded for this period yet — net profit shows once they are.</p>}
              </>
            )}
          </div>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: `color-mix(in srgb, ${C.stamp} 8%, transparent)`, color: C.stamp }}><LineChart size={18} /></span>
        </div>
        {st && <p className="mt-3 flex items-center gap-1 text-[11px]" style={{ fontFamily: F.body, fontWeight: 700, color: C.stamp }}>See breakdown & supplier comparison <ChevronRight size={12} /></p>}
      </button>
      {open && st && <ProfitLossDetail data={data} st={st} periodLabel={periodLabel} onClose={() => setOpen(false)} onGo={onGo} />}
    </>
  );
}

function ProfitLossDetail({ data, st, periodLabel, onClose, onGo }) {
  const [compare, setCompare] = useState(null);
  const [compareError, setCompareError] = useState("");
  useEffect(() => {
    api.get("/reports/supplier-comparison/").then(setCompare, (e) => setCompareError(e.message));
  }, []);
  const head = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };
  const cell = "px-3 py-2 text-right text-xs";
  const box = { backgroundColor: C.slip2, border: `1px solid ${C.rule}` };

  return (
    <DetailFrame title={`Profit & Loss — ${st.label}`} subtitle={`${periodLabel} · paid invoices only; unpaid ones are receivables`} onClose={onClose}>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["Revenue", st.revenue], ["Cost of goods", -st.cogs], ["Gross profit", st.gross_profit], ["Net profit", st.net_profit]].map(([k, v]) => (
          <div key={k} className="rounded-lg px-3 py-2" style={box}>
            <p className="text-[10px] uppercase" style={head}>{k}</p>
            <p className="text-base" style={{ fontFamily: F.mono, fontWeight: 700, color: v === null ? C.inkSoft : k === "Cost of goods" ? C.ink : tone(v) }}>{v === null ? "Needs expenses" : money(v)}</p>
          </div>
        ))}
      </div>

      <p className="mt-5 text-[11px] uppercase" style={head}>Where the profit comes from</p>
      <div className="mt-2 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full min-w-[520px] border-collapse">
          <thead style={{ backgroundColor: C.slip2 }}>
            <tr className="text-[10px] uppercase" style={head}>
              <th className="px-3 py-2 text-left">Income</th><th className="px-3 py-2 text-right">Billed</th><th className="px-3 py-2 text-right">Cost</th>
              <th className="px-3 py-2 text-right">Profit</th><th className="px-3 py-2 text-right">Margin</th>
            </tr>
          </thead>
          <tbody>
            {(st.by_kind || []).filter((k) => k.revenue !== 0).map((k) => (
              <tr key={k.kind} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, color: C.ink }}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600 }}>
                  {KIND_LABEL[k.kind]}
                  {k.kind === "service" && <span className="block text-[11px]" style={{ fontWeight: 400, color: C.inkSoft }}>Labour, visit charges, on-site work — no goods cost</span>}
                </td>
                <td className={cell} style={{ fontFamily: F.mono }}>{money(k.revenue)}</td>
                <td className={cell} style={{ fontFamily: F.mono }}>{k.cogs === null ? "—" : money(k.cogs)}</td>
                <td className={cell} style={{ fontFamily: F.mono, fontWeight: 700, color: tone(k.gross_profit) }}>{money(k.gross_profit)}</td>
                <td className={cell} style={{ fontFamily: F.mono }}>{pct(k.gross_margin_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>Refunds of {money(st.refunds)} are taken off the total revenue.</p>

      {data.stores.length > 1 && (
        <>
          <p className="mt-5 text-[11px] uppercase" style={head}>Stores side by side</p>
          <div className="mt-2 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
            <table className="w-full min-w-[520px] border-collapse">
              <thead style={{ backgroundColor: C.slip2 }}>
                <tr className="text-[10px] uppercase" style={head}>
                  <th className="px-3 py-2 text-left">Store</th><th className="px-3 py-2 text-right">Revenue</th><th className="px-3 py-2 text-right">Gross profit</th>
                  <th className="px-3 py-2 text-right">Margin</th><th className="px-3 py-2 text-right">Net profit</th>
                </tr>
              </thead>
              <tbody>
                {data.stores.map((s) => (
                  <tr key={s.store.id} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, color: C.ink }}>
                    <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600 }}>{s.store.name}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{money(s.revenue)}</td>
                    <td className={cell} style={{ fontFamily: F.mono, color: tone(s.gross_profit) }}>{money(s.gross_profit)}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{pct(s.gross_margin_pct)}</td>
                    <td className={cell} style={{ fontFamily: F.mono, fontWeight: 700, color: s.net_profit === null ? C.inkSoft : tone(s.net_profit) }}>{s.net_profit === null ? "—" : money(s.net_profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-5 flex items-center gap-1.5 text-[11px] uppercase" style={head}><Truck size={13} /> Which supplier earns us more</p>
      <ErrorNote message={compareError} />
      {!compare && !compareError && <div className="py-4"><Spinner label="Comparing suppliers…" /></div>}
      {compare && <SupplierComparison compare={compare} />}

      {onGo && (
        <button type="button" onClick={() => { onClose(); onGo("storeLocator"); }} className="mt-5 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 700, color: C.stamp }}>
          Open the full Profit & Loss (Store Locator → a store) <ArrowRight size={13} />
        </button>
      )}
    </DetailFrame>
  );
}

function SupplierComparison({ compare }) {
  const head = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };
  const cell = "px-3 py-1.5 text-right text-xs";
  if (!compare.products.length) {
    return (
      <p className="mt-2 rounded-lg p-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft, backgroundColor: C.slip2 }}>
        No supplier purchases recorded yet. Add suppliers in Parties (type Supplier), choose one under “Bought from” when adding stock,
        or use “Set supplier” on a product in Inventory for stock you already hold.
        {compare.untagged_units > 0 && ` ${compare.untagged_units} unit${compare.untagged_units === 1 ? "" : "s"} have no supplier yet.`}
      </p>
    );
  }
  return (
    <>
      {compare.suppliers.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {compare.suppliers.map((s, i) => (
            <span key={s.supplier_id} className="rounded-lg px-3 py-1.5 text-xs" style={{ fontFamily: F.body, backgroundColor: i === 0 ? `color-mix(in srgb, ${C.green} 8%, transparent)` : C.slip2, border: `1px solid ${i === 0 ? C.green : C.rule}`, color: C.ink }}>
              {i === 0 && <Award size={12} className="mr-1 inline" style={{ color: C.green }} />}<b>{s.supplier}</b> · {s.sold}/{s.bought} sold · profit <b style={{ fontFamily: F.mono, color: tone(s.profit) }}>{money(s.profit)}</b>
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 space-y-2">
        {compare.products.slice(0, 15).map((p) => (
          <div key={p.variant} className="overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <span className="text-xs" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>{p.product} <span style={{ fontWeight: 400, color: C.inkSoft }}>({p.spec}) · sells at {money(p.sell_price)}</span></span>
              {p.suppliers.length > 1 && <span className="text-[11px]" style={{ fontFamily: F.body, color: C.green, fontWeight: 700 }}>{money(p.gap_per_unit)} more per unit from {p.suppliers[0].supplier}</span>}
            </div>
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="text-[10px] uppercase" style={head}>
                  <th className="px-3 py-1.5 text-left">Supplier</th><th className="px-3 py-1.5 text-right">Bought</th><th className="px-3 py-1.5 text-right">Avg price paid</th>
                  <th className="px-3 py-1.5 text-right">Sold</th><th className="px-3 py-1.5 text-right">Avg sale</th><th className="px-3 py-1.5 text-right">Profit / unit</th>
                  <th className="px-3 py-1.5 text-right">Total profit</th>
                </tr>
              </thead>
              <tbody>
                {p.suppliers.map((r) => (
                  <tr key={r.supplier_id} style={{ borderTop: `1px solid ${C.rule}`, color: C.ink, backgroundColor: r.best ? `color-mix(in srgb, ${C.green} 5%, transparent)` : undefined }}>
                    <td className="px-3 py-1.5 text-xs" style={{ fontFamily: F.body, fontWeight: 600 }}>{r.best && <Award size={11} className="mr-1 inline" style={{ color: C.green }} />}{r.supplier}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{r.bought}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{money(r.avg_cost)}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{r.sold}</td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{r.avg_sale === null ? "—" : money(r.avg_sale)}</td>
                    <td className={cell} style={{ fontFamily: F.mono, fontWeight: 700, color: tone(r.profit_per_unit) }}>
                      {money(r.profit_per_unit)}{r.basis === "expected" && <span className="block text-[10px]" style={{ fontFamily: F.body, fontWeight: 400, color: C.inkSoft }}>expected</span>}
                    </td>
                    <td className={cell} style={{ fontFamily: F.mono }}>{r.sold ? money(r.profit) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <p className="mt-1 text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>
        Profit per unit is from units actually sold (sale price − price paid); “expected” = today's selling price − price paid, for units not sold yet.
        {compare.untagged_units > 0 && ` ${compare.untagged_units} unit${compare.untagged_units === 1 ? "" : "s"} have no supplier recorded — tag them in Inventory to include them.`}
      </p>
    </>
  );
}
