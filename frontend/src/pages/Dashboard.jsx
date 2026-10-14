
import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  LineChart,
  Line,
  Cell,
  Legend,
} from "recharts";
import {
  AlertTriangle,
  CalendarClock,
  Clock3,
  Package,
  Receipt,
  Repeat2,
  CreditCard,
  RotateCcw,
  CalendarRange,
  X,
  Wrench,
  TrendingDown,
  TrendingUp,
  Boxes,
  RefreshCw,
  SlidersHorizontal,
  CircleDollarSign,
  Activity,
  ChevronRight,
  Store,
  Globe,
} from "lucide-react";

import { C, F, compact, money } from "../lib/theme";
import { api } from "../lib/api";
import PageHeader from "../components/PageHeader";

/* -------------------------------------------------------
   PREMIUM DASHBOARD DESIGN SYSTEM
------------------------------------------------------- */

// Dashboard palette = the app theme (lib/theme.js), so the dashboard reads
// as part of the same product as the sidebar and every other page.
const UI = {
  bg: "transparent",
  surface: C.slip,
  inset: C.slip2,
  text: C.ink,
  muted: C.inkSoft,
  border: C.rule,
  primary: C.stamp,
  blue: C.blue,
  green: C.green,
  amber: C.amber,
  red: C.carbon,
  plum: "#7D5A94",
  navy: C.deep,
};

const cardStyle = {
  background: UI.surface,
  border: `1px solid ${UI.border}`,
  borderRadius: 16,
  boxShadow: "0 1px 2px rgba(35,40,31,0.04), 0 8px 24px -12px rgba(35,40,31,0.10)",
};

const font = {
  fontFamily: F.body,
};

function SectionTitle({ title, subtitle, action }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2
          className="text-base font-bold tracking-tight"
          style={{ color: UI.text, ...font }}
        >
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-xs" style={{ color: UI.muted, ...font }}>
            {subtitle}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

function Eyebrow({ children }) {
  return (
    <p
      className="text-[10px] font-bold uppercase"
      style={{
        color: UI.muted,
        letterSpacing: "0.12em",
        ...font,
      }}
    >
      {children}
    </p>
  );
}

function Pill({ color = UI.primary, children }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-bold"
      style={{
        color,
        background: `${color}12`,
        ...font,
      }}
    >
      {children}
    </span>
  );
}

function Panel({ children, className = "", style = {} }) {
  return (
    <div className={className} style={{ ...cardStyle, ...style }}>
      {children}
    </div>
  );
}

function IconTile({ icon: Icon, color = UI.primary, size = 17 }) {
  return (
    <span
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
      style={{
        color,
        background: `${color}12`,
      }}
    >
      <Icon size={size} strokeWidth={2} />
    </span>
  );
}

function ActionLink({ children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-bold transition hover:opacity-70"
      style={{ color: UI.primary, ...font }}
    >
      {children}
      <ChevronRight size={14} />
    </button>
  );
}

function Spinner({ label = "Loading dashboard..." }) {
  return (
    <div
      className="flex min-h-[300px] flex-col items-center justify-center gap-3"
      style={{ color: UI.muted, ...font }}
    >
      <span
        className="h-9 w-9 animate-spin rounded-full border-[3px]"
        style={{
          borderColor: `${UI.primary}25`,
          borderTopColor: UI.primary,
        }}
      />
      <p className="text-sm font-medium">{label}</p>
    </div>
  );
}

function ErrorNote({ message, onRetry }) {
  if (!message) return null;

  return (
    <Panel className="m-5 p-5">
      <div className="flex items-start gap-3">
        <IconTile icon={AlertTriangle} color={UI.red} />
        <div className="min-w-0 flex-1">
          <h3 className="font-bold" style={{ color: UI.text, ...font }}>
            Dashboard could not load
          </h3>
          <p className="mt-1 break-words text-sm" style={{ color: UI.muted }}>
            {message}
          </p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-lg px-3 py-2 text-xs font-bold text-white"
              style={{ background: UI.primary }}
            >
              Try again
            </button>
          )}
        </div>
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------
   KPI CARDS
------------------------------------------------------- */

function StatCard({ label, value, sub, trend, icon: Icon, color }) {
  return (
    <Panel className="group min-w-0 p-3.5 transition duration-200 hover:-translate-y-0.5 hover:shadow-lg sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Eyebrow>{label}</Eyebrow>
          <p
            className="mt-3 break-words text-xl font-extrabold tracking-tight sm:text-[28px]"
            style={{
              color: UI.text,
              fontFamily: F.display,
            }}
          >
            {value ?? "—"}
          </p>
        </div>
        <span className="hidden sm:block">
          <IconTile icon={Icon} color={color} />
        </span>
      </div>

      {sub && (
        <div
          className="mt-3 flex min-h-5 items-center gap-1.5 text-xs font-medium"
          style={{ color: trend ? (trend === "down" ? UI.red : UI.green) : UI.muted, ...font }}
        >
          {trend === "up" && <TrendingUp size={13} />}
          {trend === "down" && <TrendingDown size={13} />}
          {!trend && <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />}
          <span>{sub}</span>
        </div>
      )}

      <div
        className="mt-4 h-1 overflow-hidden rounded-full"
        style={{ background: `${color}12` }}
      >
        <div
          className="h-full w-1/3 rounded-full transition-all duration-500 group-hover:w-2/3"
          style={{ background: color }}
        />
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------
   CHART STYLES
------------------------------------------------------- */

const tooltipStyle = {
  background: UI.surface,
  border: `1px solid ${UI.border}`,
  borderRadius: 12,
  boxShadow: "0 8px 28px rgba(35, 40, 31, 0.12)",
  fontFamily: F.body,
  fontSize: 12,
};

function ChartFrame({ children, height = 250 }) {
  return (
    <div style={{ width: "100%", height }}>
      {children}
    </div>
  );
}

/* -------------------------------------------------------
   RECURRING RENTAL ISSUES
------------------------------------------------------- */

function RecurringIssues({ byUnit = [], byModel = [], onGo }) {
  if (!byUnit.length && !byModel.length) return null;

  return (
    <Panel className="mt-5 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5"
        style={{ borderColor: UI.border }}>
        <div className="flex items-center gap-3">
          <IconTile icon={RotateCcw} color={UI.red} />
          <div>
            <h2 className="font-bold" style={{ color: UI.text, ...font }}>
              Recurring rental issues
            </h2>
            <p className="mt-1 text-xs" style={{ color: UI.muted }}>
              Identify repeat faults before they become costly.
            </p>
          </div>
        </div>
        <ActionLink onClick={() => onGo("rentals")}>
          View rentals
        </ActionLink>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2">
        <div className="p-5">
          <Eyebrow>Same physical unit</Eyebrow>
          <div className="mt-3 space-y-3">
            {byUnit.map((r) => (
              <div
                key={r.rental_id}
                className="rounded-xl p-3.5"
                style={{ border: `1px solid ${UI.border}`, background: UI.inset }}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-bold" style={{ color: UI.text }}>
                    {r.party}
                  </p>
                  <Pill color={UI.red}>{r.issue_count}× raised</Pill>
                </div>
                <p className="mt-1 text-xs" style={{ color: UI.muted }}>
                  {r.product}
                </p>
                <p className="mt-2 text-xs leading-5" style={{ color: UI.muted }}>
                  Latest: {r.latest_issue}
                  {r.open_count > 0 && ` · ${r.open_count} still open`}
                </p>
              </div>
            ))}
            {!byUnit.length && (
              <p className="text-sm" style={{ color: UI.muted }}>
                No repeat complaints for individual units.
              </p>
            )}
          </div>
        </div>

        <div className="p-5 sm:border-l" style={{ borderColor: UI.border }}>
          <Eyebrow>Same model, different units</Eyebrow>
          <div className="mt-3 space-y-3">
            {byModel.map((m) => (
              <div
                key={m.product}
                className="rounded-xl p-3.5"
                style={{ border: `1px solid ${UI.border}`, background: UI.inset }}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-bold" style={{ color: UI.text }}>
                    {m.product}
                  </p>
                  <Pill color={UI.amber}>{m.issue_count} issues</Pill>
                </div>
                <p className="mt-2 text-xs" style={{ color: UI.muted }}>
                  Across {m.affected_units} unit{m.affected_units !== 1 ? "s" : ""}
                  {" · "}{m.open_count} still open
                </p>
              </div>
            ))}
            {!byModel.length && (
              <p className="text-sm" style={{ color: UI.muted }}>
                No recurring model-level issues.
              </p>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------
   MAIN DASHBOARD
------------------------------------------------------- */

// A date the filter can actually use: empty (no bound) or a complete,
// real YYYY-MM-DD in a sane range. While someone types the year into a
// native date input the value passes through 0002-, 0020-, 0202-... --
// those must never reach the API.
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
function isUsableDate(value) {
  if (!value) return true;
  const m = DATE_RE.exec(value);
  if (!m) return false;
  const [y, mo, d] = m.slice(1).map(Number);
  if (y < 2000 || y > 2100) return false;
  const dt = new Date(Date.UTC(y, mo - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}

function rangeProblem(from, to, fromIncomplete = false, toIncomplete = false) {
  if (fromIncomplete || !isUsableDate(from)) return "Enter a complete start date (year 2000 or later).";
  if (toIncomplete || !isUsableDate(to)) return "Enter a complete end date (year 2000 or later).";
  if (from && to && from > to) return "Start date can't be after the end date.";
  return "";
}

const fmtFilterDate = (v) =>
  v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "";

export default function Dashboard({ onGo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [stockPoints, setStockPoints] = useState([]);
  // What the inputs show while being edited...
  const [draftFrom, setDraftFrom] = useState("");
  const [draftTo, setDraftTo] = useState("");
  // ...and the range the dashboard is actually filtered by.
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // A half-filled native date input reports value "" (same as cleared);
  // validity.badInput is the only way to tell the two apart.
  const [fromIncomplete, setFromIncomplete] = useState(false);
  const [toIncomplete, setToIncomplete] = useState(false);
  const [channel, setChannel] = useState("all");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    api.get("/stock-points/")
      .then((d) => {
        if (active) setStockPoints(d.results ?? d);
      })
      .catch(() => {
        if (active) setStockPoints([]);
      });

    return () => {
      active = false;
    };
  }, []);

  const draftProblem = rangeProblem(draftFrom, draftTo, fromIncomplete, toIncomplete);

  // Apply the typed range once it is complete and valid, after a short
  // pause, so a half-typed date never triggers a request.
  useEffect(() => {
    if (draftProblem) return undefined;
    if (draftFrom === dateFrom && draftTo === dateTo) return undefined;
    const t = setTimeout(() => {
      setDateFrom(draftFrom);
      setDateTo(draftTo);
    }, 450);
    return () => clearTimeout(t);
  }, [draftFrom, draftTo, draftProblem, dateFrom, dateTo]);

  const applyNow = () => {
    if (draftProblem) return;
    setDateFrom(draftFrom);
    setDateTo(draftTo);
  };

  useEffect(() => {
    // `active` drops a response that arrives after a newer request was
    // started, so an older, slower response can't overwrite newer results.
    let active = true;
    setLoading(true);
    setError("");

    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (channel !== "all") params.set("channel", channel);
    const qs = params.toString();

    api.get(`/dashboard/summary/${qs ? `?${qs}` : ""}`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e) => {
        if (active) setError(e.message || "An unexpected error occurred.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [dateFrom, dateTo, channel, refreshKey]);

  const filtersActive = Boolean(dateFrom || dateTo || draftFrom || draftTo || channel !== "all");

  const clearFilters = () => {
    setDraftFrom("");
    setDraftTo("");
    setFromIncomplete(false);
    setToIncomplete(false);
    setDateFrom("");
    setDateTo("");
    setChannel("all");
  };

  const retry = () => setRefreshKey((k) => k + 1);

  // First load failed: nothing to show yet.
  if (error && !data) {
    return (
      <div className="cb-dash min-h-full flex-1 overflow-y-auto p-4 sm:p-8" style={{ background: UI.bg }}>
        <ErrorNote message={error} onRetry={retry} />
      </div>
    );
  }

  // First load only. Later reloads keep the page (and the filter inputs
  // someone is typing in) on screen and show a small "Updating" state.
  if (!data) {
    return (
      <div className="min-h-full flex-1" style={{ background: UI.bg }}>
        <Spinner />
      </div>
    );
  }

  const sections = data.sections || {};
  const visibleSections = Object.entries(sections)
    .filter(([, enabled]) => enabled)
    .map(([key]) => key);

  const sectionLabel = {
    stock: "Stock",
    sales: "Sales",
    repairs: "Repairs",
    rentals: "Rentals",
  };

  const lowStock = data.low_stock || [];
  const stageCounts = data.repair_stage_counts || {};
  const churn = data.churn_leaderboard || [];

  const selectedChannel =
    stockPoints.find((s) => s.slug === channel)?.name || channel;

  return (
    <div
      className="cb-dash min-h-full min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-7 sm:py-7 xl:px-9"
      aria-busy={loading}
      style={{ background: UI.bg }}
    >
      {/* HEADER */}
      <div className="mb-6">
        <div className="mb-2 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: UI.green }} />
          <span className="text-[10px] font-bold uppercase tracking-[0.15em]"
            style={{ color: UI.green }}>
            Business overview
          </span>
        </div>

        <PageHeader
          title="Dashboard"
          subtitle={`${visibleSections.map((s) => sectionLabel[s]).join(" · ") || "No sections visible"} · Live business insights`}
          actions={
            <button
              type="button"
              onClick={retry}
              disabled={loading}
              title="Refresh data"
              className="inline-flex h-9 items-center gap-2 rounded-xl px-3 text-xs font-bold transition hover:-translate-y-0.5 disabled:cursor-wait disabled:opacity-70"
              style={{
                ...cardStyle,
                color: UI.text,
                fontFamily: F.body,
              }}
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">{loading ? "Updating…" : "Refresh data"}</span>
            </button>
          }
        />
      </div>

      {/* FILTER BAR */}
      <Panel className="mb-6 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <IconTile icon={SlidersHorizontal} color={UI.primary} size={16} />
            <div>
              <h2 className="text-sm font-bold" style={{ color: UI.text }}>
                Refine your overview
              </h2>
              <p className="mt-0.5 text-[11px]" style={{ color: UI.muted }}>
                Filter your business data by period and channel.
              </p>
            </div>
          </div>

          {filtersActive && (
            <button
              type="button"
              onClick={clearFilters}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-bold"
              style={{ color: UI.red, background: `${UI.red}0D` }}
            >
              <X size={13} />
              Reset
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-semibold" style={{ color: UI.muted }}>
              Start date
            </span>
            <div data-field className="flex items-center gap-2 rounded-xl px-3"
              style={{ border: `1px solid ${UI.border}`, background: UI.inset }}>
              <CalendarRange size={15} style={{ color: UI.muted }} />
              <input
                data-bare
                type="date"
                value={draftFrom}
                min="2000-01-01"
                // a max also caps the year field at 4 digits (Chrome allows 6)
                max={draftTo && isUsableDate(draftTo) ? draftTo : "2100-12-31"}
                onChange={(e) => {
                  setDraftFrom(e.target.value);
                  setFromIncomplete(e.target.validity.badInput);
                }}
                // clearing the last segment fires no change event, so
                // re-read the field's state when focus leaves it
                onBlur={(e) => {
                  setFromIncomplete(e.target.validity.badInput);
                  applyNow();
                }}
                onKeyDown={(e) => e.key === "Enter" && applyNow()}
                aria-invalid={fromIncomplete || !isUsableDate(draftFrom)}
                className="w-full min-w-0 bg-transparent py-2.5 text-xs outline-none"
                style={{ color: UI.text, ...font }}
              />
            </div>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-semibold" style={{ color: UI.muted }}>
              End date
            </span>
            <div data-field className="flex items-center gap-2 rounded-xl px-3"
              style={{ border: `1px solid ${UI.border}`, background: UI.inset }}>
              <CalendarRange size={15} style={{ color: UI.muted }} />
              <input
                data-bare
                type="date"
                value={draftTo}
                min={draftFrom && isUsableDate(draftFrom) ? draftFrom : "2000-01-01"}
                max="2100-12-31"
                onChange={(e) => {
                  setDraftTo(e.target.value);
                  setToIncomplete(e.target.validity.badInput);
                }}
                onBlur={(e) => {
                  setToIncomplete(e.target.validity.badInput);
                  applyNow();
                }}
                onKeyDown={(e) => e.key === "Enter" && applyNow()}
                aria-invalid={toIncomplete || !isUsableDate(draftTo) || Boolean(draftFrom && draftTo && draftFrom > draftTo)}
                className="w-full min-w-0 bg-transparent py-2.5 text-xs outline-none"
                style={{ color: UI.text, ...font }}
              />
            </div>
          </label>

          <label className="block sm:col-span-2 xl:col-span-1">
            <span className="mb-1.5 block text-[11px] font-semibold" style={{ color: UI.muted }}>
              Sales channel
            </span>
            <div data-field className="flex items-center gap-2 rounded-xl px-3"
              style={{ border: `1px solid ${UI.border}`, background: UI.inset }}>
              <Store size={15} style={{ color: UI.muted }} />
              <select
                data-bare
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                className="w-full min-w-0 bg-transparent py-2.5 text-xs outline-none"
                style={{ color: UI.text, ...font }}
              >
                <option value="all">All channels</option>
                {stockPoints.map((s) => (
                  <option key={s.slug} value={s.slug}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          </label>

          <div className="flex items-end sm:col-span-2 xl:col-span-1" aria-live="polite">
            <div
              className="flex w-full items-center gap-2 rounded-xl px-3 py-3"
              style={{ background: `${UI.primary}08`, border: `1px solid ${UI.primary}15` }}
            >
              <Activity size={15} style={{ color: UI.primary }} />
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: UI.primary }}>
                  {loading ? "Updating…" : "Current view"}
                </p>
                <p className="truncate text-xs font-semibold" style={{ color: UI.text }}>
                  {dateFrom || dateTo || channel !== "all"
                    ? `${fmtFilterDate(dateFrom) || "All time"} → ${fmtFilterDate(dateTo) || "Today"}${channel !== "all" ? ` · ${selectedChannel}` : ""}`
                    : "All dates · All channels"}
                </p>
              </div>
            </div>
          </div>
        </div>
        {(draftProblem || error) && (
          <p
            role="alert"
            className="mt-3 flex items-start gap-1.5 text-xs font-semibold"
            style={{ color: UI.red }}
          >
            <AlertTriangle size={13} className="mt-px shrink-0" />
            <span>
              {draftProblem || `Couldn't refresh the dashboard: ${error}`}
              {!draftProblem && (
                <button type="button" onClick={retry} className="ml-2 underline">
                  Try again
                </button>
              )}
            </span>
          </p>
        )}
      </Panel>

      {/* KPI CARDS */}
      <SectionTitle
        title="Business at a glance"
        subtitle="Key metrics from your current selection"
      />

      <div className="mb-7 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,150px),1fr))] sm:[grid-template-columns:repeat(auto-fill,minmax(210px,1fr))]">
        {sections.sales && (
          <StatCard
            label="Paid sales revenue"
            value={compact(data.revenue_paid)}
            icon={Receipt}
            color={UI.primary}
          />
        )}
        {sections.repairs && (
          <StatCard
            label="Repair revenue"
            value={compact(data.repair_revenue_paid)}
            sub={`${data.repair_invoice_count} repair bills`}
            icon={Wrench}
            color={UI.blue}
          />
        )}
        {sections.sales && (
          <StatCard
            label="Pending collections"
            value={compact(data.pending_collections)}
            sub={`${data.open_invoice_count} invoices open`}
            trend={data.open_invoice_count ? "down" : undefined}
            icon={CreditCard}
            color={UI.amber}
          />
        )}
        {sections.stock && (
          <StatCard
            label="Stock on hand"
            value={`${data.total_stock_units} units`}
            sub={`${compact(data.stock_value)} inventory at cost`}
            icon={Package}
            color={UI.green}
          />
        )}
        {sections.stock && (
          <StatCard
            label="Low stock alerts"
            value={data.low_stock_count}
            sub="4 units or fewer"
            trend={data.low_stock_count ? "down" : undefined}
            icon={AlertTriangle}
            color={UI.red}
          />
        )}
        {sections.rentals && (
          <StatCard
            label="Rental churn risk"
            value={data.rentals_at_risk}
            sub={`${data.rental_device_count ?? data.rental_count} devices · ${data.rental_count} agreements`}
            trend={data.rentals_at_risk ? "down" : undefined}
            icon={Repeat2}
            color={UI.plum}
          />
        )}
        {sections.rentals && data.rentals_pending_approval > 0 && (
          <StatCard
            label="Pending rental approvals"
            value={data.rentals_pending_approval}
            sub="Awaiting customer decision"
            trend="down"
            icon={CalendarClock}
            color={UI.amber}
          />
        )}
        {sections.repairs && data.repair_overdue_count > 0 && (
          <StatCard
            label="Overdue repairs"
            value={data.repair_overdue_count}
            sub="Past expected delivery date"
            trend="down"
            icon={Clock3}
            color={UI.red}
          />
        )}
      </div>

      {/* REVENUE CHART + STOCK ALERTS */}
      {(sections.sales || sections.stock) && (
        <div className="mb-5 grid grid-cols-1 gap-5 xl:grid-cols-5">
          {sections.sales && data.monthly_revenue && (
            <Panel className="flex min-w-0 flex-col p-4 sm:p-5 xl:col-span-3">
              <SectionTitle
                title="Revenue performance"
                subtitle="Paid sales, repairs and rentals · Last 6 months"
                action={
                  <span className="rounded-lg px-2.5 py-1.5 text-[10px] font-bold"
                    style={{ color: UI.green, background: `${UI.green}10` }}>
                    Paid invoices
                  </span>
                }
              />

              <div className="min-h-[260px] flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data.monthly_revenue}
                    margin={{ top: 10, right: 8, left: -12, bottom: 0 }}
                  >
                    <CartesianGrid
                      stroke={UI.border}
                      strokeDasharray="4 5"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="month"
                      tick={{ fontSize: 10, fill: UI.muted }}
                      axisLine={false}
                      tickLine={false}
                      dy={8}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: UI.muted }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={compact}
                      width={52}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(v) => money(v)}
                    />
                    <Legend
                      wrapperStyle={{
                        fontSize: 11,
                        fontFamily: F.body,
                        paddingTop: 10,
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="sales"
                      name="Sales"
                      stroke={UI.primary}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, strokeWidth: 0 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="repairs"
                      name="Repairs"
                      stroke={UI.blue}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, strokeWidth: 0 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="rentals"
                      name="Rentals"
                      stroke={UI.green}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, strokeWidth: 0 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          )}

          {sections.stock && (
            <Panel className={`min-w-0 p-4 sm:p-5 ${sections.sales && data.monthly_revenue ? "xl:col-span-2" : "xl:col-span-5"}`}>
              <SectionTitle
                title="Stock health"
                subtitle="Items that need your attention"
                action={
                  <span className="rounded-lg px-2 py-1 text-[10px] font-bold"
                    style={{ color: UI.red, background: `${UI.red}10` }}>
                    {data.low_stock_count} alerts
                  </span>
                }
              />

              <div className="space-y-1">
                {lowStock.slice(0, 6).map((item, i) => (
                  <div
                    key={`${item.variant_code}-${i}`}
                    className="flex items-center gap-3 rounded-xl px-2 py-3 transition hover:bg-[#F7F3EA]"
                  >
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                      style={{ background: `${UI.amber}14`, color: UI.amber }}
                    >
                      <Boxes size={16} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-bold" style={{ color: UI.text }}>
                        {item.product}
                      </p>
                      <p className="mt-1 truncate text-[10px]" style={{ color: UI.muted }}>
                        {item.variant_code} · {item.spec}
                      </p>
                    </div>

                    <div className="text-right">
                      <p className="text-sm font-extrabold" style={{ color: item.total_stock <= 2 ? UI.red : UI.amber }}>
                        {item.total_stock}
                      </p>
                      <p className="text-[9px]" style={{ color: UI.muted }}>
                        remaining
                      </p>
                    </div>
                  </div>
                ))}

                {!lowStock.length && (
                  <div className="py-10 text-center">
                    <IconTile icon={Package} color={UI.green} />
                    <p className="mt-3 text-sm font-semibold" style={{ color: UI.text }}>
                      All clear
                    </p>
                    <p className="mt-1 text-xs" style={{ color: UI.muted }}>
                      No critical stock items.
                    </p>
                  </div>
                )}
              </div>

              <div className="mt-3 border-t pt-3" style={{ borderColor: UI.border }}>
                <ActionLink onClick={() => onGo("inventory")}>
                  Open inventory
                </ActionLink>
              </div>
            </Panel>
          )}
        </div>
      )}

      {/* REPAIR PIPELINE */}
      {sections.repairs && data.repair_stage_counts && (
        <Panel className="mb-5 p-4 sm:p-5">
          <SectionTitle
            title="Repair operations"
            subtitle="Current workload across repair stages"
            action={
              <ActionLink onClick={() => onGo("repairs")}>
                Manage repairs
              </ActionLink>
            }
          />

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {Object.entries(stageCounts).map(([stage, count], i) => {
              const colors = [UI.primary, UI.blue, UI.amber, UI.green];
              const color = stage === "Delivered" ? UI.green : colors[i % colors.length];

              return (
                <div
                  key={stage}
                  className="rounded-xl p-4"
                  style={{ border: `1px solid ${UI.border}`, background: UI.inset }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold" style={{ color: UI.muted }}>
                      {stage}
                    </p>
                    <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                  </div>
                  <p
                    className="mt-3 text-2xl font-extrabold"
                    style={{ color: UI.text, fontFamily: F.display }}
                  >
                    {count}
                  </p>
                  <div className="mt-3 h-1 overflow-hidden rounded-full" style={{ background: `${color}18` }}>
                    <div className="h-full w-1/2 rounded-full" style={{ background: color }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      {/* RENTAL CHURN */}
      {sections.rentals && (
        <Panel className="mb-5 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5"
            style={{ borderColor: UI.border }}>
            <div className="flex items-center gap-3">
              <IconTile icon={Repeat2} color={UI.plum} />
              <div>
                <h2 className="font-bold" style={{ color: UI.text }}>
                  Rental customer health
                </h2>
                <p className="mt-1 text-xs" style={{ color: UI.muted }}>
                  Prioritise agreements that may need intervention.
                </p>
              </div>
            </div>
            <ActionLink onClick={() => onGo("rentals")}>
              View all rentals
            </ActionLink>
          </div>

          <div className="p-4 sm:p-5">
            {churn.length > 0 ? (
              <div className="space-y-1">
                {churn.map((r, i) => {
                  const color =
                    r.band === "High risk"
                      ? UI.red
                      : r.band === "Watch"
                      ? UI.amber
                      : UI.green;

                  return (
                    <div
                      key={`${r.party}-${i}`}
                      className="flex flex-wrap items-center gap-3 rounded-xl px-3 py-3 transition hover:bg-[#F7F3EA]"
                    >
                      <div
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold"
                        style={{ background: `${color}12`, color }}
                      >
                        {String(r.party || "?").slice(0, 1).toUpperCase()}
                      </div>

                      <div className="min-w-0 flex-1 basis-[calc(100%-4rem)] sm:basis-0">
                        <p className="truncate text-sm font-bold" style={{ color: UI.text }}>
                          {r.party}
                        </p>
                        <p className="mt-1 truncate text-xs" style={{ color: UI.muted }}>
                          {r.product}
                        </p>
                      </div>

                      <div className="ml-12 flex items-center gap-3 sm:ml-0">
                        <div className="hidden w-20 sm:block">
                          <div className="h-1.5 overflow-hidden rounded-full" style={{ background: UI.border }}>
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${Math.min(100, Math.max(0, Number(r.score) || 0))}%`,
                                background: color,
                              }}
                            />
                          </div>
                        </div>
                        <span className="w-12 text-right text-xs font-bold" style={{ color: UI.text }}>
                          {r.score}/100
                        </span>
                        <Pill color={color}>{r.band}</Pill>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="py-8 text-center">
                <p className="text-sm font-semibold" style={{ color: UI.text }}>
                  No rental risk records yet
                </p>
                <p className="mt-1 text-xs" style={{ color: UI.muted }}>
                  Customer risk information will appear here when available.
                </p>
              </div>
            )}
          </div>
        </Panel>
      )}

      {/* RECURRING ISSUES */}
      {sections.rentals && (
        <RecurringIssues
          byUnit={data.recurring_issues_by_unit || []}
          byModel={data.recurring_issues_by_model || []}
          onGo={onGo}
        />
      )}

      {/* CHANNEL REVENUE */}
      {sections.sales && (
        <SalesByChannel channelSales={data.channel_sales || []} />
      )}

      <div className="pb-3 pt-7 text-center">
        <p className="text-[10px] font-medium tracking-wide" style={{ color: UI.muted }}>
          BUSINESS OVERVIEW · LIVE API DATA
        </p>
      </div>
    </div>
  );
}

/* -------------------------------------------------------
   SALES BY CHANNEL
------------------------------------------------------- */

function SalesByChannel({ channelSales = [] }) {
  const shops = channelSales.filter((c) => c.kind === "shop");
  const online = channelSales.filter((c) => c.kind === "online");

  const chartData = [...channelSales].sort(
    (a, b) => b.revenue_paid - a.revenue_paid
  );

  return (
    <div className="mt-7">
      <SectionTitle
        title="Sales channel intelligence"
        subtitle="Compare paid revenue across physical shops and online channels."
      />

      <Panel className="overflow-hidden">
        <div className="p-4 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <IconTile icon={CircleDollarSign} color={UI.primary} />
              <div>
                <h3 className="text-sm font-bold" style={{ color: UI.text }}>
                  Revenue contribution
                </h3>
                <p className="mt-1 text-xs" style={{ color: UI.muted }}>
                  Paid revenue by individual channel
                </p>
              </div>
            </div>

            <div className="flex gap-3">
              <span className="flex items-center gap-1.5 text-[10px] font-semibold" style={{ color: UI.muted }}>
                <span className="h-2 w-2 rounded-sm" style={{ background: UI.primary }} />
                Shops
              </span>
              <span className="flex items-center gap-1.5 text-[10px] font-semibold" style={{ color: UI.muted }}>
                <span className="h-2 w-2 rounded-sm" style={{ background: UI.blue }} />
                Online
              </span>
            </div>
          </div>

          {chartData.length > 0 ? (
            <ChartFrame height={Math.max(200, chartData.length * 38)}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={chartData}
                  layout="vertical"
                  margin={{ top: 4, right: 15, left: 8, bottom: 4 }}
                  barCategoryGap="30%"
                >
                  <CartesianGrid
                    stroke={UI.border}
                    strokeDasharray="4 5"
                    horizontal={false}
                  />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 10, fill: UI.muted }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={compact}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={115}
                    tick={{ fontSize: 11, fill: UI.text }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => money(value)}
                  />
                  <Bar dataKey="revenue_paid" name="Paid revenue" radius={[0, 6, 6, 0]}>
                    {chartData.map((c) => (
                      <Cell
                        key={c.id}
                        fill={c.kind === "shop" ? UI.primary : UI.blue}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartFrame>
          ) : (
            <p className="py-12 text-center text-sm" style={{ color: UI.muted }}>
              No channel sales available for this period.
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 border-t sm:grid-cols-2" style={{ borderColor: UI.border }}>
          <ChannelTable title="Physical shops" rows={shops} icon={Store} color={UI.primary} />
          <ChannelTable title="Online channels" rows={online} icon={Globe} color={UI.blue} />
        </div>
      </Panel>
    </div>
  );
}

function ChannelTable({ title, rows, icon: Icon, color }) {
  const totalRevenue = rows.reduce((sum, c) => sum + Number(c.revenue_paid || 0), 0);

  return (
    <div className="min-w-0 p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <IconTile icon={Icon} color={color} size={15} />
          <Eyebrow>{title}</Eyebrow>
        </div>
        <span className="text-xs font-bold" style={{ color: UI.text }}>
          {money(totalRevenue)}
        </span>
      </div>

      <div>
        {rows.map((c) => (
          <div
            key={c.id}
            className="flex items-center justify-between gap-3 border-t py-3"
            style={{ borderColor: UI.border }}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-bold" style={{ color: UI.text }}>
                {c.name}
              </p>
              <p className="mt-1 text-[10px]" style={{ color: UI.muted }}>
                {c.invoice_count} invoices · {c.units_sold} units
              </p>
            </div>

            <div className="shrink-0 text-right">
              <p className="text-xs font-bold" style={{ color: UI.text }}>
                {money(c.revenue_paid)}
              </p>
              {c.pending > 0 && (
                <p className="mt-1 text-[10px] font-semibold" style={{ color: UI.amber }}>
                  {money(c.pending)} pending
                </p>
              )}
            </div>
          </div>
        ))}

        {!rows.length && (
          <p className="py-5 text-center text-xs" style={{ color: UI.muted }}>
            No channels of this type.
          </p>
        )}
      </div>
    </div>
  );
}