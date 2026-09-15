import { useEffect, useState } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from "recharts";
import { AlertTriangle, Package, Receipt, Repeat2, CreditCard, RotateCcw, CalendarRange, X, Wrench } from "lucide-react";
import { C, F, compact, money } from "../lib/theme";
import { api } from "../lib/api";
import { StatCard, Eyebrow, Pill, Spinner, ErrorNote } from "../components/Atoms";

/* Chart-shaped series the backend doesn't have enough transaction
   history to compute yet -- swap for a real /api/dashboard/trends/
   endpoint once there are a few months of invoices to aggregate. */
const MONTHS_14 = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"];
const seeded = (i) => { const x = Math.sin(i * 999.77) * 10000; return Math.abs(x - Math.floor(x)); };
const INCOME_TREND = MONTHS_14.map((m, i) => ({
  month: m,
  Sales: Math.round(180 + seeded(i * 2) * 90) / 10,
  Rental: Math.round(95 + seeded(i * 3 + 1) * 40) / 10,
  Parts: Math.round(45 + seeded(i * 5 + 2) * 30) / 10,
  Repairs: Math.round(35 + seeded(i * 7 + 3) * 25) / 10,
}));

function MiniDonut({ data, colors, centerLabel, centerSub }) {
  return (
    <div style={{ height: 170 }} className="relative">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={2} stroke="none">
            {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
          </Pie>
          <Tooltip contentStyle={{ fontFamily: F.body, fontSize: 12, background: C.slip, border: `1px solid ${C.rule}`, color: C.ink }} />
        </PieChart>
      </ResponsiveContainer>
      {centerLabel && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{centerLabel}</span>
          {centerSub && <span style={{ fontFamily: F.mono, fontSize: 10, color: C.inkSoft }}>{centerSub}</span>}
        </div>
      )}
    </div>
  );
}

function RecurringIssues({ byUnit, byModel, onGo }) {
  if (!byUnit.length && !byModel.length) return null;
  return (
    <div className="mt-4" data-panel style={{ border: `1px solid ${C.carbon}`, backgroundColor: `${C.carbon}0A` }}>
      <div className="flex items-center justify-between p-4 pb-0">
        <p className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>
          <RotateCcw size={14} style={{ color: C.carbon }} /> Recurring issues on rented laptops
        </p>
        <button onClick={() => onGo("rentals")} className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>View rentals →</button>
      </div>
      <p className="px-4 pt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        Units or models a client keeps coming back about — worth a swap or a stock inspection, not just another repair.
      </p>

      <div className="grid grid-cols-1 gap-0 sm:grid-cols-2">
        <div className="p-4">
          <Eyebrow>Same physical unit, repeat complaints</Eyebrow>
          <div className="mt-2 space-y-2">
            {byUnit.map((r) => (
              <div key={r.rental_id} className="px-3 py-2.5" style={{ backgroundColor: C.slip }}>
                <div className="flex items-center justify-between">
                  <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.party}</p>
                  <Pill color={C.carbon}>{r.issue_count}× raised</Pill>
                </div>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.product}</p>
                <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Latest: "{r.latest_issue}" {r.open_count > 0 && `· ${r.open_count} still open`}</p>
              </div>
            ))}
            {!byUnit.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No single unit has repeat complaints right now.</p>}
          </div>
        </div>

        <div className="p-4" style={{ borderTop: `1px solid ${C.rule}` }}>
          <Eyebrow>Same model, different units/clients</Eyebrow>
          <div className="mt-2 space-y-2">
            {byModel.map((m) => (
              <div key={m.product} className="px-3 py-2.5" style={{ backgroundColor: C.slip }}>
                <div className="flex items-center justify-between">
                  <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{m.product}</p>
                  <Pill color={C.amber}>{m.issue_count} issues</Pill>
                </div>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Across {m.affected_units} unit{m.affected_units !== 1 ? "s" : ""} · {m.open_count} still open</p>
              </div>
            ))}
            {!byModel.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No model has issues spread across multiple units right now.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard({ onGo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [stockPoints, setStockPoints] = useState([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [channel, setChannel] = useState("all");

  useEffect(() => {
    api.get("/stock-points/").then((d) => setStockPoints(d.results ?? d));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (channel !== "all") params.set("channel", channel);
    const qs = params.toString();
    api.get(`/dashboard/summary/${qs ? `?${qs}` : ""}`).then(setData).catch((e) => setError(e.message));
  }, [dateFrom, dateTo, channel]);

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!data) return <Spinner label="Loading dashboard…" />;

  const filtersActive = dateFrom || dateTo || channel !== "all";
  const clearFilters = () => { setDateFrom(""); setDateTo(""); setChannel("all"); };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 24, color: C.ink }}>Business overview</p>
          <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Live from the API -- stock, revenue, and churn risk update as data changes</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, padding: 12 }}>
        <div className="flex items-center gap-1.5">
          <CalendarRange size={14} style={{ color: C.inkSoft }} />
          <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: C.inkSoft }}>Filter</span>
        </div>
        <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>From
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1 block bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>
        <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>To
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1 block bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>
        <label className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Channel
          <select value={channel} onChange={(e) => setChannel(e.target.value)} className="mt-1 block bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
            <option value="all">All channels</option>
            {stockPoints.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
        </label>
        {filtersActive && (
          <button onClick={clearFilters} className="flex items-center gap-1 px-2 py-1.5 text-xs" style={{ fontFamily: F.body, color: C.carbon, border: `1px solid ${C.carbon}` }}>
            <X size={11} /> Clear
          </button>
        )}
        {filtersActive && (
          <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
            Showing {dateFrom || "the start"} → {dateTo || "today"}{channel !== "all" ? ` · ${stockPoints.find((s) => s.slug === channel)?.name || channel} only` : ""}
          </span>
        )}
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <StatCard label="Sales revenue, paid" value={compact(data.revenue_paid)} icon={Receipt} />
        <StatCard label="Repair revenue, paid" value={compact(data.repair_revenue_paid)} sub={`${data.repair_invoice_count} repair bill${data.repair_invoice_count !== 1 ? "s" : ""}`} icon={Wrench} />
        <StatCard label="Pending collections" value={compact(data.pending_collections)} sub={`${data.open_invoice_count} invoices open`} trend={data.open_invoice_count ? "down" : undefined} icon={CreditCard} />
        <StatCard label="Stock on hand" value={`${data.total_stock_units} units`} sub={`${compact(data.stock_value)} at cost`} icon={Package} />
        <StatCard label="Low stock alerts" value={data.low_stock_count} sub="4 units or fewer" trend={data.low_stock_count ? "down" : undefined} icon={AlertTriangle} />
        <StatCard label="Rentals at churn risk" value={data.rentals_at_risk} sub={`of ${data.rental_count} active rentals`} trend={data.rentals_at_risk ? "down" : undefined} icon={Repeat2} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div data-panel className="p-4" style={{ border: `1px solid ${C.orange}`, backgroundColor: C.slip }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>Income trend -- monthly</p>
          <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>demo series -- wire to real historicals once available</p>
          <div className="mt-3" style={{ height: 230 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={INCOME_TREND}>
                <CartesianGrid stroke={C.rule} vertical={false} />
                <XAxis dataKey="month" tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={{ stroke: C.rule }} tickLine={false} />
                <YAxis tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={false} tickLine={false} tickFormatter={(v) => `₹${v}L`} width={40} />
                <Tooltip contentStyle={{ fontFamily: F.body, fontSize: 12, background: C.slip2, border: `1px solid ${C.rule}`, color: C.ink }} />
                <Legend wrapperStyle={{ fontFamily: F.body, fontSize: 11, color: C.inkSoft }} />
                <Line type="monotone" dataKey="Rental" stroke={C.blue} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="Sales" stroke={C.stamp} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="Parts" stroke={C.green} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="Repairs" stroke={C.amber} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div data-panel className="p-4" style={{ border: `1px solid ${C.orange}`, backgroundColor: C.slip }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>Low stock, act soon</p>
          <div className="mt-3 space-y-2">
            {data.low_stock.slice(0, 6).map((item, i) => (
              <div key={i} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <div className="min-w-0">
                  <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{item.product}</p>
                  <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{item.variant_code} · {item.spec}</p>
                </div>
                <Pill color={C.carbon}>{item.total_stock} left</Pill>
              </div>
            ))}
            {!data.low_stock.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Nothing critical right now.</p>}
            <button onClick={() => onGo("inventory")} className="mt-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>View inventory →</button>
          </div>
        </div>
      </div>

      <div className="mt-4" data-panel style={{ border: `1px solid ${C.orange}`, backgroundColor: C.slip }}>
        <div className="flex items-center justify-between p-4 pb-0">
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>Customer churn risk -- rentals</p>
          <button onClick={() => onGo("rentals")} className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>View rentals →</button>
        </div>
        <div className="p-4 space-y-2">
          {data.churn_leaderboard.map((r, i) => (
            <div key={i} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
              <div className="min-w-0">
                <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.party}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.product}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.score}/100</span>
                <Pill color={r.band === "High risk" ? C.carbon : r.band === "Watch" ? C.amber : C.green}>{r.band}</Pill>
              </div>
            </div>
          ))}
          {!data.churn_leaderboard.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No rentals yet.</p>}
        </div>
      </div>

      <RecurringIssues byUnit={data.recurring_issues_by_unit} byModel={data.recurring_issues_by_model} onGo={onGo} />

      <SalesByChannel channelSales={data.channel_sales} />
    </div>
  );
}

function SalesByChannel({ channelSales }) {
  const shops = channelSales.filter((c) => c.kind === "shop");
  const online = channelSales.filter((c) => c.kind === "online");
  const chartData = [...channelSales].sort((a, b) => b.revenue_paid - a.revenue_paid);

  return (
    <>
      <p className="mt-8 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
        Sales by channel -- shops and every online channel, separately
      </p>

      <div className="mt-3" data-panel style={{ border: `1px solid ${C.orange}`, backgroundColor: C.slip }}>
        <div className="p-4">
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>Paid revenue by channel</p>
          <div className="mt-3" style={{ height: Math.max(180, chartData.length * 34) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid stroke={C.rule} horizontal={false} />
                <XAxis type="number" tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={false} tickLine={false} tickFormatter={compact} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fontFamily: F.body, fontSize: 11, fill: C.ink }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ fontFamily: F.body, fontSize: 12, background: C.slip2, border: `1px solid ${C.rule}`, color: C.ink }} formatter={(v) => money(v)} />
                <Bar dataKey="revenue_paid" radius={[0, 3, 3, 0]}>
                  {chartData.map((c, i) => <Cell key={i} fill={c.kind === "shop" ? C.stamp : C.blue} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex gap-4">
            <span className="flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}><span style={{ width: 8, height: 8, backgroundColor: C.stamp, display: "inline-block", borderRadius: 999 }} />Shops</span>
            <span className="flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}><span style={{ width: 8, height: 8, backgroundColor: C.blue, display: "inline-block", borderRadius: 999 }} />Online channels</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-0 sm:grid-cols-2" style={{ borderTop: `1px solid ${C.rule}` }}>
          <ChannelTable title="Shops" rows={shops} borderRight />
          <ChannelTable title="Online channels" rows={online} />
        </div>
      </div>
    </>
  );
}

function ChannelTable({ title, rows, borderRight }) {
  return (
    <div className="p-4" style={borderRight ? { borderRight: `1px solid ${C.rule}` } : undefined}>
      <Eyebrow>{title}</Eyebrow>
      <div className="mt-2">
        {rows.map((c) => (
          <div key={c.id} className="flex items-center justify-between py-2" style={{ borderBottom: `1px solid ${C.rule}` }}>
            <div className="min-w-0">
              <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{c.name}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{c.invoice_count} invoice{c.invoice_count !== 1 ? "s" : ""} · {c.units_sold} units</p>
            </div>
            <div className="text-right">
              <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(c.revenue_paid)}</p>
              {c.pending > 0 && <p className="text-xs" style={{ fontFamily: F.mono, color: C.amber }}>{money(c.pending)} pending</p>}
            </div>
          </div>
        ))}
        {!rows.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No channels of this type.</p>}
      </div>
    </div>
  );
}
