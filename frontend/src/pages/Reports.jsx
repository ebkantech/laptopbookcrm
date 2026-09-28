import { useEffect, useState } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  LineChart, Line, Cell,
} from "recharts";
import { Landmark, TrendingUp, Receipt, CreditCard, Repeat2, CalendarClock, AlertTriangle, Wrench, Clock3, Users, Star, Boxes } from "lucide-react";
import { C, F, compact, money, heavyPanel } from "../lib/theme";
import { api } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { StatCard, Pill, Spinner, ErrorNote, TabBar } from "../components/Atoms";
import { useSession } from "../context/SessionContext";

// Task 7: business reporting suite. Built one report at a time per the
// doc's own recommended order -- Financial + Sales first, then Rentals.
// Each tab is its own API call so adding the remaining reports later is
// just another tab + another fetch, not a rework of this page's shape.
//
// Each report has its own required permission, matching the doc's "Who
// sees it" column exactly (see reports/views.py for why they differ --
// Financial/Sales need reports.export, Rental portfolio needs
// rentals.view since Sales Staff holds that but not reports.export).
// The nav item in App.jsx already lets a user in if they hold ANY of
// these; this per-tab check is what actually hides the reports they
// individually can't see, so "hide AND block" holds here too.
const ALL_TABS = [
  { id: "financial", label: "Financial summary", icon: Landmark, perm: "reports.export" },
  { id: "sales", label: "Sales summary", icon: Receipt, perm: "reports.export" },
  { id: "rentals", label: "Rental portfolio", icon: Repeat2, perm: "rentals.view" },
  { id: "repairs", label: "Repair turnaround", icon: Wrench, perm: "repairs.view" },
  { id: "parties", label: "Party report", icon: Users, perm: "parties.view" },
  { id: "feedback", label: "Feedback & engagement", icon: Star, perm: "portal.manage" },
  { id: "inventory", label: "Inventory & stock", icon: Boxes, perm: "inventory.edit" },
];

export default function Reports() {
  const { can } = useSession();
  const tabs = ALL_TABS.filter((t) => can(t.perm));
  const [tab, setTab] = useState(tabs[0]?.id);

  if (!tabs.length) {
    return (
      <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8" style={{ backgroundColor: C.paper }}>
        <PageHeader title="Reports" subtitle="Financial and sales figures, live from the API" />
        <div className="mt-4"><ErrorNote message="No reports are available for your role yet." /></div>
      </div>
    );
  }

  const active = tab && tabs.some((t) => t.id === tab) ? tab : tabs[0].id;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8" style={{ backgroundColor: C.paper }}>
      <PageHeader title="Reports" subtitle="Financial and sales figures, live from the API" />
      <div className="mt-4">
        <TabBar tabs={tabs} value={active} onChange={setTab} />
      </div>
      <div className="mt-5">
        {active === "financial" && <FinancialSummary />}
        {active === "sales" && <SalesSummary />}
        {active === "rentals" && <RentalPortfolio />}
        {active === "repairs" && <RepairTurnaround />}
        {active === "parties" && <PartyReport />}
        {active === "feedback" && <FeedbackEngagement />}
        {active === "inventory" && <InventoryStock />}
      </div>
    </div>
  );
}

function MonthlyRevenueChart({ data, title, sub, dataKey = "revenue", label = "Revenue" }) {
  return (
    <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
      <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>{title}</p>
      {sub && <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{sub}</p>}
      <div className="mt-3" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid stroke={C.rule} vertical={false} />
            <XAxis dataKey="month" tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={{ stroke: C.rule }} tickLine={false} />
            <YAxis tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={false} tickLine={false} tickFormatter={compact} width={52} />
            <Tooltip contentStyle={{ fontFamily: F.body, fontSize: 12, background: C.slip, border: `1px solid ${C.rule}`, color: C.ink }} formatter={(v) => money(v)} />
            <Line type="monotone" dataKey={dataKey} name={label} stroke={C.stamp} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function FinancialSummary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/financial-summary/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading financial summary…" />;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Outstanding" value={compact(data.outstanding_total)} sub={`${data.outstanding_count} invoice${data.outstanding_count !== 1 ? "s" : ""} unpaid`} trend={data.outstanding_count ? "down" : undefined} icon={CreditCard} />
        <StatCard label="Active rentals, monthly value" value={compact(data.rentals_active_monthly_value)} sub={`${data.rentals_active_count} agreement${data.rentals_active_count !== 1 ? "s" : ""}`} icon={Repeat2} />
        {data.rentals_pending_approval > 0 && (
          <StatCard label="Rentals pending approval" value={data.rentals_pending_approval} sub="waiting on customer decision" trend="down" icon={CalendarClock} />
        )}
      </div>
      <div className="mt-4">
        <MonthlyRevenueChart
          data={data.monthly_revenue}
          title="Revenue by month — paid invoices"
          sub="last 12 months"
        />
      </div>
    </div>
  );
}

function SalesSummary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/sales-summary/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading sales summary…" />;

  const chartData = [...data.by_stock_point].sort((a, b) => b.revenue_paid - a.revenue_paid);

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Revenue, paid" value={compact(data.total_revenue_paid)} sub="last 12 months" icon={TrendingUp} />
        <StatCard label="Paid invoices" value={data.total_invoices} icon={Receipt} />
      </div>

      <div className="mt-4">
        <MonthlyRevenueChart
          data={data.monthly_revenue}
          title="Revenue by month — paid invoices"
          sub="last 12 months"
        />
      </div>

      <div className="mt-4 p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Revenue by stock point</p>
        <div className="mt-3" style={{ height: Math.max(180, chartData.length * 34) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ left: 8 }}>
              <CartesianGrid stroke={C.rule} horizontal={false} />
              <XAxis type="number" tick={{ fontFamily: F.mono, fontSize: 10, fill: C.inkSoft }} axisLine={false} tickLine={false} tickFormatter={compact} />
              <YAxis type="category" dataKey="name" width={120} tick={{ fontFamily: F.body, fontSize: 11, fill: C.ink }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ fontFamily: F.body, fontSize: 12, background: C.slip, border: `1px solid ${C.rule}`, color: C.ink }} formatter={(v) => money(v)} />
              <Bar dataKey="revenue_paid" radius={[0, 3, 3, 0]}>
                {chartData.map((c, i) => <Cell key={i} fill={c.kind === "shop" ? C.stamp : C.blue} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-3 space-y-2">
          {data.by_stock_point.map((sp) => (
            <div key={sp.id} className="flex items-center justify-between py-2" style={{ borderBottom: `1px solid ${C.rule}` }}>
              <div className="min-w-0">
                <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{sp.name}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{sp.invoice_count} invoice{sp.invoice_count !== 1 ? "s" : ""} · {sp.units_sold} units</p>
              </div>
              <div className="text-right">
                <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(sp.revenue_paid)}</p>
                {sp.pending > 0 && <Pill color={C.amber}>{money(sp.pending)} pending</Pill>}
              </div>
            </div>
          ))}
          {!data.by_stock_point.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No stock points yet.</p>}
        </div>
      </div>
    </div>
  );
}

function RentalPortfolio() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/rental-portfolio/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading rental portfolio…" />;

  const bandColor = { "High risk": C.carbon, "Watch": C.amber, "Healthy": C.green };

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Active + approved" value={data.live_count} sub="agreements" icon={Repeat2} />
        <StatCard label="Monthly recurring value" value={compact(data.monthly_recurring_value)} icon={TrendingUp} />
        <StatCard label="Overdue" value={data.overdue_count} sub="past next payment date" trend={data.overdue_count ? "down" : undefined} icon={CalendarClock} />
        {data.churn_band_counts["High risk"] > 0 && (
          <StatCard label="High churn risk" value={data.churn_band_counts["High risk"]} sub="worth a call" trend="down" icon={AlertTriangle} />
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>By status</p>
          <div className="mt-3 space-y-2">
            {Object.entries(data.status_counts).filter(([, count]) => count > 0).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <p className="text-sm capitalize" style={{ fontFamily: F.body, color: C.ink }}>{status.replace(/_/g, " ")}</p>
                <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{count}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Churn risk — active + approved</p>
          <div className="mt-3 space-y-2">
            {Object.entries(data.churn_band_counts).map(([band, count]) => (
              <div key={band} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <Pill color={bandColor[band]}>{band}</Pill>
                <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{count}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Churn leaderboard — top 20</p>
        <div className="mt-3 space-y-2">
          {data.leaderboard.map((r) => (
            <div key={r.id} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
              <div className="min-w-0">
                <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.party}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.product} · {money(r.monthly_fee)}/mo{r.overdue ? " · overdue" : ""}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.score}/100</span>
                <Pill color={bandColor[r.band]}>{r.band}</Pill>
              </div>
            </div>
          ))}
          {!data.leaderboard.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No active or approved rentals yet.</p>}
        </div>
      </div>
    </div>
  );
}

function RepairTurnaround() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/repair-turnaround/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading repair turnaround…" />;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard
          label="Avg. turnaround"
          value={data.avg_turnaround_days != null ? `${data.avg_turnaround_days} days` : "—"}
          sub={`${data.settled_count} settled ticket${data.settled_count !== 1 ? "s" : ""}, received → delivered`}
          icon={Clock3}
        />
        <StatCard label="Open tickets" value={data.open_count} sub="not yet delivered" icon={Wrench} />
        <StatCard label="Overdue" value={data.overdue_count} sub="past the expected date" trend={data.overdue_count ? "down" : undefined} icon={CalendarClock} />
      </div>

      <div className="mt-4 p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Ticket queue by stage</p>
        <div className="mt-3 flex flex-wrap gap-3">
          {Object.entries(data.stage_counts).map(([stage, count]) => (
            <div key={stage} className="min-w-[140px] flex-1 rounded-lg px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{stage}</p>
              <p className="mt-0.5 text-xl" style={{ fontFamily: F.display, fontWeight: 800, color: stage === "Delivered" ? C.inkSoft : C.ink }}>{count}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PartyReport() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/party-report/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading party report…" />;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total parties" value={data.total_parties} icon={Users} />
        <StatCard label="With purchases" value={data.customers_with_purchases} icon={Receipt} />
        <StatCard label="Repeat customers" value={data.repeat_customers_count} icon={Repeat2} />
        <StatCard label="One-time customers" value={data.one_time_customers_count} sub="worth a follow-up" icon={CalendarClock} />
      </div>

      <div className="mt-4 p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Top customers by spend</p>
        <div className="mt-3 space-y-2">
          {data.top_customers.map((p) => (
            <div key={p.id} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
              <div className="min-w-0">
                <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{p.name}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.type} · {p.invoice_count} invoice{p.invoice_count !== 1 ? "s" : ""}</p>
              </div>
              <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(p.total_spent)}</p>
            </div>
          ))}
          {!data.top_customers.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No customers with purchases yet.</p>}
        </div>
      </div>
    </div>
  );
}

function FeedbackEngagement() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/feedback-engagement/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading feedback & engagement…" />;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Feedback entries" value={data.feedback_count} icon={Star} />
        <StatCard label="Average rating" value={data.avg_rating != null ? `${data.avg_rating}/5` : "—"} icon={Star} />
        <StatCard label="Unique portal visitors" value={data.unique_parties_accessed} icon={Users} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Rating breakdown</p>
          <div className="mt-3 space-y-2">
            {Object.entries(data.rating_counts).reverse().map(([star, count]) => (
              <div key={star} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <p className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{star} star{star !== "1" ? "s" : ""}</p>
                <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{count}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Recent feedback</p>
          <div className="mt-3 space-y-2">
            {data.recent_feedback.map((f, i) => (
              <div key={i} className="py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <div className="flex items-center justify-between">
                  <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{f.party}</p>
                  <Pill color={C.amber}>{f.rating}/5</Pill>
                </div>
                {f.comment && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{f.comment}</p>}
              </div>
            ))}
            {!data.recent_feedback.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No feedback yet.</p>}
          </div>
        </div>
      </div>

      <div className="mt-4">
        <MonthlyRevenueChart
          data={data.portal_access_by_month}
          title="Portal access by month"
          sub="last 12 months"
          dataKey="count"
          label="Visits"
        />
      </div>
    </div>
  );
}

function InventoryStock() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/reports/inventory-stock/").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading inventory & stock…" />;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total stock units" value={data.total_stock_units} icon={Boxes} />
        <StatCard label="Stock value" value={compact(data.stock_value)} icon={Landmark} />
        <StatCard label="Low stock variants" value={data.low_stock_count} sub="≤4 units" trend={data.low_stock_count ? "down" : undefined} icon={AlertTriangle} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>By stock point</p>
          <div className="mt-3 space-y-2">
            {data.by_stock_point.map((sp) => (
              <div key={sp.name} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{sp.name}</p>
                <div className="text-right">
                  <p className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{sp.units} units</p>
                  <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{money(sp.value)}</p>
                </div>
              </div>
            ))}
            {!data.by_stock_point.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No stock points yet.</p>}
          </div>
        </div>

        <div className="p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Low stock — ≤4 units</p>
          <div className="mt-3 space-y-2">
            {data.low_stock.map((v) => (
              <div key={v.variant_code} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
                <div className="min-w-0">
                  <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{v.product}</p>
                  <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{v.variant_code} · {v.spec}</p>
                </div>
                <Pill color={v.total_stock === 0 ? C.carbon : C.amber}>{v.total_stock} left</Pill>
              </div>
            ))}
            {!data.low_stock.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Nothing running low.</p>}
          </div>
        </div>
      </div>

      <div className="mt-4 p-4" style={{ ...heavyPanel, borderRadius: 14 }}>
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>Rental assets by status</p>
        <div className="mt-3 flex flex-wrap gap-3">
          {Object.entries(data.rental_asset_counts).map(([status, count]) => (
            <div key={status} className="min-w-[120px] flex-1 rounded-lg px-3 py-2.5 capitalize" style={{ backgroundColor: C.slip2 }}>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{status}</p>
              <p className="mt-0.5 text-xl" style={{ fontFamily: F.display, fontWeight: 800, color: C.ink }}>{count}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
