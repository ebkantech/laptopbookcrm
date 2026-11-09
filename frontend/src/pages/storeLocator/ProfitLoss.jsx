import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, ArrowLeft, BarChart3, Building2, CalendarRange, ChevronLeft, ChevronRight, Coins, Info, Landmark, Lock,
  Package, Percent, ReceiptText, RefreshCw, Scale, TrendingDown, TrendingUp, Wallet,
} from "lucide-react";
import { api } from "../../lib/api";
import { C, F, compact, money } from "../../lib/theme";
import { PillButton } from "../../components/Atoms";
import { Badge, KindBadge, Panel, Segmented, SelectPill, Skel, StateBox, StoreMark } from "./shared";
import { num, plural } from "./format";

/*
 * Store-wise Profit & Loss (Store Locator -> a store -> Profit & Loss).
 *
 * Every figure is computed by the backend (reports.profit_loss) for one
 * store the account is authorised for -- this file only formats it:
 *   GET /reports/profit-loss/?store=<id>&period=..          statement, trend, monthly
 *   GET /reports/profit-loss/transactions/?store=<id>&..     the records behind it
 *   GET /reports/profit-loss/stores/?period=..               side by side (all-store accounts)
 * Shown only to accounts the API marks can_view_profit_loss; anyone else
 * gets a 403 from every one of these endpoints.
 */

const PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "this_week", label: "This week" },
  { id: "this_month", label: "This month" },
  { id: "last_month", label: "Last month" },
  { id: "this_year", label: "This year" },
  { id: "custom", label: "Custom" },
];
const SOURCE_LABEL = { sale: "Product sales", repair: "Repairs", rental: "Rentals", onsite: "On-site service" };
const TX_KINDS = [
  { id: "settled", label: "Counted invoices" },
  { id: "expenses", label: "Expenses" },
  { id: "refunds", label: "Refunds" },
  { id: "receivables", label: "Unpaid" },
  { id: "cancelled", label: "Cancelled" },
];
const PAGE_SIZE = 25;
// Revenue / cost of goods: the validated blue-amber pair; profit uses the status pair by sign.
const SERIES = { revenue: C.stamp, cogs: C.amber, expenses: "#6D5BD0", profit: C.green, loss: C.carbon };

/* ---------------------------------------------------------------- *
 * Formatting
 * ---------------------------------------------------------------- */

const signed = (n) => (n === null || n === undefined ? "Unavailable" : n < 0 ? `−${money(-n)}` : money(n));
// why expenses / net profit have no figure (reports.profit_loss expense_status)
const EXPENSE_GAP = {
  unavailable: "Expense records aren't set up on this server yet",
  none_recorded: "No expenses recorded for this period",
};
const pctText = (p) => (p === null || p === undefined ? "—" : `${p.startsWith("-") ? "−" + p.slice(1) : p}%`);
const tone = (n) => (n > 0 ? "green" : n < 0 ? "red" : "grey");

function parseDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}
const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const shortDay = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const monthFmt = new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit" });
const fmtDay = (iso) => dayFmt.format(parseDay(iso));

function periodText(period) {
  if (!period) return "";
  return period.start === period.end ? fmtDay(period.start) : `${fmtDay(period.start)} – ${fmtDay(period.end)}`;
}

function stampText(iso, timeZone) {
  try {
    return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone }).format(new Date(iso)) + ` ${timeZone}`;
  } catch {
    return new Date(iso).toLocaleString("en-IN");
  }
}

const bucketLabel = (iso, granularity) => (granularity === "month" ? monthFmt.format(parseDay(iso)) : shortDay.format(parseDay(iso)));

function query(store, period, extra = {}) {
  const q = new URLSearchParams({ period: period.key, ...extra });
  if (store) q.set("store", store);
  if (period.key === "custom") {
    q.set("date_from", period.from);
    q.set("date_to", period.to);
  }
  return q.toString();
}

/* ---------------------------------------------------------------- *
 * Data
 * ---------------------------------------------------------------- */

// The last response stays on screen while the next one loads (`loading`);
// a response for an older path or reload never overwrites a newer one.
function useFetch(path) {
  const [state, setState] = useState({ path: null, tick: -1, data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let current = true;
    api.get(path).then(
      (data) => { if (current) setState({ path, tick, data, error: null }); },
      (error) => { if (current) setState({ path, tick, data: null, error }); },
    );
    return () => { current = false; };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: state.data, error: state.error, loading: state.path !== path || state.tick !== tick, reload };
}

/* ---------------------------------------------------------------- *
 * Pieces
 * ---------------------------------------------------------------- */

function PeriodBar({ period, current, onChange }) {
  const [draft, setDraft] = useState({ from: period.from || "", to: period.to || "" });
  const invalid = !draft.from || !draft.to || draft.from > draft.to;
  const pick = (key) => {
    if (key !== "custom") return onChange({ key });
    // start the custom range from the period on screen, so it shows figures at once
    const next = invalid && current ? { from: current.start, to: current.end } : draft;
    setDraft(next);
    onChange({ key, ...next, pending: !next.from || !next.to || next.from > next.to });
  };
  return (
    <div className="pl-periods">
      <Segmented label="Reporting period" value={period.key} onChange={pick} options={PERIODS} />
      {period.key === "custom" && (
        <form className="pl-custom" onSubmit={(e) => { e.preventDefault(); if (!invalid) onChange({ key: "custom", ...draft }); }}>
          <label className="pl-date"><span>From</span>
            <input type="date" value={draft.from} max={draft.to || undefined} onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))} required />
          </label>
          <label className="pl-date"><span>To</span>
            <input type="date" value={draft.to} min={draft.from || undefined} onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))} required />
          </label>
          <button type="submit" className="sl-view-btn" disabled={invalid}><CalendarRange size={14} aria-hidden="true" />Apply</button>
          {draft.from && draft.to && draft.from > draft.to && <span className="pl-err" role="alert">The end date can't be before the start date.</span>}
        </form>
      )}
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, sub, tone: t = "blue", flag, loading }) {
  return (
    <div className="pl-card" data-tone={t}>
      <div className="pl-card-top">
        <span className="pl-card-icon"><Icon size={17} aria-hidden="true" /></span>
        {flag && <Badge tone="amber" icon={AlertTriangle}>{flag}</Badge>}
      </div>
      {loading ? (
        <><Skel w="55%" h={26} className="mt-3 block" /><Skel w="75%" h={10} className="mt-2 block" /></>
      ) : (
        <>
          <p className="pl-card-value" data-muted={typeof value !== "string" || !/[\d]/.test(value)}>{value}</p>
          <p className="pl-card-label">{label}</p>
          {sub && <p className="pl-card-sub">{sub}</p>}
        </>
      )}
    </div>
  );
}

// How far cost of goods can be trusted (reports.profit_loss): complete | estimated | incomplete
const RELIABILITY = {
  complete: { label: "Real costs", tone: "green" },
  estimated: { label: "Partly estimated", tone: "amber" },
  incomplete: { label: "Costs missing", tone: "red" },
};
const reliabilityOf = (q) => q.reliability || (q.cogs_complete ? "complete" : "incomplete");

function DataQuality({ st, period }) {
  const q = st.data_quality;
  const level = reliabilityOf(q);
  const notes = [];
  if (q.missing_cost_lines > 0) notes.push(`${plural(q.missing_cost_lines, "bill line")} worth ${money(q.missing_cost_value)} sold goods with no purchase cost entered. They count as free, so profit is overstated — enter the costs in Inventory → Costs (spare parts too).`);
  if (q.unlinked_sale_value > 0) notes.push(`${money(q.unlinked_sale_value)} of sale lines aren't linked to a product, so what those goods cost is unknown.`);
  if (q.estimated_cost_lines > 0) notes.push(`${plural(q.estimated_cost_lines, "bill line")} (${money(q.estimated_value)} of sales) use an estimated cost of ${money(q.estimated_cost)} — 78% of the selling price, because the real cost wasn't entered when the stock was added. Enter real costs in Inventory → Costs; sales from then on use them.`);
  if (q.service_revenue > 0) notes.push(`${money(q.service_revenue)} is labour, visit charges or rent, which have no goods cost; staff salaries and rent paid belong in Accounting → Expenses. Parts used on a repair count only where "Our cost" was entered on its line.`);
  if (q.cost_basis === "locked_at_sale") notes.push("Each bill line keeps the cost its goods had when it was billed (the average purchase cost of the stock), so correcting a cost later never changes past profit.");
  if (q.expense_status === "unavailable") notes.push("Expense records aren't available on this server yet (the expense database migration hasn't been applied), so expenses and net profit can't be shown.");
  else if (!q.expenses_recorded) notes.push("No expenses are recorded for this store in this period. That isn't the same as zero expenses, so net profit is shown as unavailable until rent, salaries and other costs are recorded in Accounting → Expenses.");
  if (period && !period.complete) notes.push("This period hasn't ended yet, so expenses for it may still be added.");
  notes.push("Invoices store one gross amount with no tax component, so any GST collected is included in revenue.");
  return (
    <div className="pl-quality" role="note">
      <span className="pl-quality-icon"><Info size={16} aria-hidden="true" /></span>
      <div className="min-w-0">
        <p className="pl-quality-title">
          {level === "incomplete" ? "Some goods have no cost — profit is overstated"
            : level === "estimated" ? "Some costs are estimates — profit is approximate"
              : q.expenses_recorded ? "How far these figures go" : "Real product costs · expenses not recorded"}
          {" "}<Badge tone={RELIABILITY[level].tone}>{RELIABILITY[level].label}</Badge>
        </p>
        <ul>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </div>
    </div>
  );
}

function ChartBox({ title, icon, legend, empty, emptyTitle, emptyText, children, height = 260 }) {
  return (
    <Panel icon={icon} title={title}>
      {empty ? (
        <StateBox compact icon={BarChart3} title={emptyTitle || "No settled transactions in this period"} text={emptyText || "Charts appear once invoices are paid at this store."} />
      ) : (
        <>
          {legend}
          <div className="pl-chart" style={{ height }}>{children}</div>
        </>
      )}
    </Panel>
  );
}

const axisTick = { fontFamily: F.mono, fontSize: 10, fill: C.inkSoft };
const tooltipStyle = { fontFamily: F.body, fontSize: 12, background: C.slip, border: `1px solid ${C.rule}`, borderRadius: 9, color: C.ink };

function MoneyTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ ...tooltipStyle, padding: "0.5rem 0.65rem" }}>
      <p style={{ fontWeight: 700, marginBottom: 4 }}>{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: p.color || p.payload.fill }} />
          <span style={{ color: C.inkSoft }}>{p.name}</span>
          <b style={{ marginLeft: "auto", fontFamily: F.mono, fontWeight: 600 }}>{p.value === null || p.value === undefined ? "Not available" : signed(p.value)}</b>
        </p>
      ))}
    </div>
  );
}

function LegendRow({ items }) {
  return (
    <ul className="pl-legend">
      {items.map((i) => (
        <li key={i.label}><span data-shape={i.shape || "bar"} style={{ background: i.color }} aria-hidden="true" />{i.label}</li>
      ))}
    </ul>
  );
}

function RevenueVsCosts({ trend }) {
  const data = trend.points.map((p) => ({ ...p, label: bucketLabel(p.bucket, trend.granularity) }));
  const empty = data.every((p) => !p.revenue && !p.cogs && !p.expenses);
  return (
    <ChartBox title="Revenue vs costs" icon={BarChart3} empty={empty}
      legend={<LegendRow items={[{ label: "Revenue", color: SERIES.revenue }, { label: "Cost of goods", color: SERIES.cogs }, { label: "Expenses", color: SERIES.expenses }]} />}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
          <CartesianGrid stroke={C.rule} vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: C.rule }} tickLine={false} minTickGap={14} interval="preserveStartEnd" />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} tickFormatter={compact} width={56} />
          <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgba(49,87,213,0.06)" }} />
          <Bar dataKey="revenue" name="Revenue" fill={SERIES.revenue} radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="cogs" name="Cost of goods" fill={SERIES.cogs} radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="expenses" name="Expenses" fill={SERIES.expenses} radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function ProfitTrend({ trend }) {
  const data = trend.points.map((p) => ({ ...p, label: bucketLabel(p.bucket, trend.granularity) }));
  const noExpenses = data.every((p) => p.net_profit === null);
  const empty = noExpenses || data.every((p) => !p.revenue && !p.cogs && !p.expenses);
  return (
    <ChartBox title={`Net profit / loss by ${trend.granularity}`} icon={TrendingUp} empty={empty}
      emptyTitle={noExpenses ? "Net profit needs expense records" : undefined}
      emptyText={noExpenses ? "No expenses are recorded for this period, so net profit isn't charted." : undefined}
      legend={<LegendRow items={[{ label: "Profit", color: SERIES.profit }, { label: "Loss", color: SERIES.loss }]} />}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={C.rule} vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: C.rule }} tickLine={false} minTickGap={14} interval="preserveStartEnd" />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} tickFormatter={compact} width={56} />
          <ReferenceLine y={0} stroke={C.ruleStrong} />
          <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgba(49,87,213,0.06)" }} />
          <Bar dataKey="net_profit" name="Net profit" radius={[4, 4, 0, 0]} maxBarSize={28}>
            {data.map((p) => <Cell key={p.bucket} fill={p.net_profit < 0 ? SERIES.loss : SERIES.profit} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function MonthlyPerformance({ monthly }) {
  const data = monthly.map((p) => ({ ...p, label: bucketLabel(p.bucket, "month") }));
  const empty = data.every((p) => !p.revenue && !p.cogs && !p.expenses);
  return (
    <ChartBox title="Monthly performance" icon={CalendarRange} empty={empty} height={280}
      legend={<LegendRow items={[
        { label: "Revenue", color: SERIES.revenue }, { label: "Cost of goods", color: SERIES.cogs },
        { label: "Expenses", color: SERIES.expenses }, { label: "Net profit", color: SERIES.profit, shape: "line" },
      ]} />}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
          <CartesianGrid stroke={C.rule} vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: C.rule }} tickLine={false} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} tickFormatter={compact} width={56} />
          <ReferenceLine y={0} stroke={C.ruleStrong} />
          <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgba(49,87,213,0.06)" }} />
          <Bar dataKey="revenue" name="Revenue" fill={SERIES.revenue} radius={[4, 4, 0, 0]} maxBarSize={30} />
          <Bar dataKey="cogs" name="Cost of goods" fill={SERIES.cogs} radius={[4, 4, 0, 0]} maxBarSize={30} />
          <Bar dataKey="expenses" name="Expenses" fill={SERIES.expenses} radius={[4, 4, 0, 0]} maxBarSize={30} />
          <Line type="monotone" dataKey="net_profit" name="Net profit" stroke={SERIES.profit} strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2, stroke: C.slip, fill: SERIES.profit }} activeDot={{ r: 5, strokeWidth: 0 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function SourceMix({ st }) {
  const rows = st.by_source.filter((r) => r.billed || r.refunds);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.revenue)));
  return (
    <Panel icon={Coins} title="Revenue by source">
      {rows.length ? (
        <ul className="sl-bars">
          {rows.map((r) => (
            <li key={r.source}>
              <div className="sl-bars-row">
                <span className="sl-bars-name">{SOURCE_LABEL[r.source]} <span className="sl-bars-spec">· {plural(r.invoices, "invoice")}</span></span>
                <span className="sl-bars-qty">{signed(r.revenue)}</span>
              </div>
              <span className="sl-bar" aria-hidden="true"><span style={{ width: `${Math.max(2, (Math.abs(r.revenue) / max) * 100)}%` }} /></span>
              {st.revenue > 0 && <p className="pl-mini">{pctText(((r.revenue * 100) / st.revenue).toFixed(1))} of revenue{r.refunds ? ` · ${money(r.refunds)} refunded` : ""}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <StateBox compact icon={Coins} title="No revenue in this period" />
      )}
    </Panel>
  );
}

function Line_({ label, value, kind, note, indent }) {
  return (
    <div className="pl-line" data-kind={kind} data-indent={indent || undefined}>
      <span className="pl-line-label">{label}{note && <span className="pl-line-note">{note}</span>}</span>
      <span className="pl-line-value" data-tone={kind === "total" && typeof value === "number" ? tone(value) : undefined}>
        {typeof value === "number" ? signed(value) : <span className="sl-empty">{value}</span>}
      </span>
    </div>
  );
}

/* The statement, laid out like a P&L: each line, then its subtotal. */
function Statement({ st }) {
  // income by what was billed: service charges are kept apart from goods
  const kind = Object.fromEntries((st.by_kind || []).map((k) => [k.kind, k]));
  const partsCost = kind.parts?.cogs || 0;
  const productCost = st.cogs - partsCost; // includes restocked returns
  const has = (k) => kind[k] && kind[k].revenue !== 0;
  return (
    <Panel icon={ReceiptText} title="Profit & Loss statement" className="sl-span-2">
      <div className="pl-statement">
        <p className="pl-sec">Revenue</p>
        {st.by_kind ? (
          <>
            <Line_ indent label="Product sales" value={kind.products?.revenue || 0} note="Laptops & accessories sold" />
            <Line_ indent label="Spare parts (repair & on-site)" value={kind.parts?.revenue || 0} note="Parts fitted on jobs" />
            <Line_ indent label="Service charges" value={kind.service?.revenue || 0} note="Labour, visit charges, on-site work — no goods cost" />
            {has("rent") && <Line_ indent label="Rent" value={kind.rent.revenue} />}
            {has("discounts") && <Line_ indent label="Less: discounts" value={kind.discounts.revenue} />}
          </>
        ) : st.by_source.map((r) => <Line_ key={r.source} indent label={SOURCE_LABEL[r.source]} value={r.billed} note={plural(r.invoices, "paid invoice")} />)}
        <Line_ indent label="Less: refunds & returns" value={-st.refunds} note={plural(st.refund_count, "refund")} />
        <Line_ kind="sub" label="Net revenue" value={st.revenue} />
        <p className="pl-sec">Cost of goods sold</p>
        <Line_ indent label="Products sold, less restocked returns" value={-productCost} note="Cost locked on each bill line when it was billed" />
        <Line_ indent label="Spare parts on repair & on-site jobs" value={partsCost ? -partsCost : "None entered"} note="Part costs, and “Our cost” typed on repair lines" />
        <Line_ kind="total" label="Gross profit" value={st.gross_profit} note={`Gross margin ${pctText(st.gross_margin_pct)}`} />
        {has("products") && <Line_ indent label="of which products" value={kind.products.gross_profit} note={`Margin ${pctText(kind.products.gross_margin_pct)}`} />}
        {has("parts") && <Line_ indent label="of which spare parts" value={kind.parts.gross_profit} note={`Margin ${pctText(kind.parts.gross_margin_pct)}`} />}
        {has("service") && <Line_ indent label="of which service charges" value={kind.service.gross_profit} note="All profit — staff wages are expenses below" />}
        {has("rent") && <Line_ indent label="of which rent" value={kind.rent.gross_profit} />}
        <p className="pl-sec">Expenses</p>
        <Line_ indent label="Operating expenses" value={st.operating_expenses === null ? "Unavailable" : -st.operating_expenses} note="Rent, salaries, utilities…" />
        <Line_ indent label="Other expenses" value={st.other_expenses === null ? "Unavailable" : -st.other_expenses}
          note={st.expenses === null ? EXPENSE_GAP[st.data_quality.expense_status] : `${plural(st.expense_count, "expense")} recorded · claimable GST excluded`} />
        <Line_ kind="total" label={st.net_profit < 0 ? "Net loss" : "Net profit / loss"} value={st.net_profit === null ? "Unavailable" : st.net_profit}
          note={st.net_profit === null ? "Needs the period's expense records" : `Net margin ${pctText(st.net_margin_pct)}`} />
        <p className="pl-sec">Not in the figures above</p>
        <Line_ indent label="Unpaid invoices (receivables)" value={st.receivables.amount} note={plural(st.receivables.count, "invoice")} />
        <Line_ indent label="Cancelled invoices" value={st.cancelled.amount} note={plural(st.cancelled.count, "invoice")} />
      </div>
    </Panel>
  );
}

// Keyed by store + period by its parent, so either change starts again at page 1.
function Transactions({ storeId, period }) {
  const [kind, setKindState] = useState("settled");
  const [source, setSourceState] = useState("");
  const [page, setPage] = useState(1);
  const setKind = (k) => { setKindState(k); setPage(1); };
  const setSource = (v) => { setSourceState(v); setPage(1); };
  const qs = query(storeId, period, { kind, page: String(page), page_size: String(PAGE_SIZE), ...(source ? { source } : {}) });
  const fetched = useFetch(`/reports/profit-loss/transactions/?${qs}`);
  const { error, loading, reload } = fetched;
  // never render one transaction type's rows under another type's columns
  const data = fetched.data?.kind === kind ? fetched.data : null;
  const pages = data ? Math.max(1, Math.ceil(data.count / data.page_size)) : 1;
  const refunds = kind === "refunds";
  const expenseRows = kind === "expenses";

  return (
    <Panel icon={Wallet} title="Underlying transactions" className="sl-span-2"
      action={data && <span className="sl-note">{plural(data.count, refunds ? "refund" : expenseRows ? "expense" : "invoice")}</span>}>
      <div className="sl-tools">
        <Segmented label="Transaction type" value={kind} onChange={setKind} options={TX_KINDS} />
        {!expenseRows && <SelectPill label="Source" value={source} onChange={setSource}>
          <option value="">All sources</option>
          <option value="sale">Product sales</option>
          <option value="repair">Repairs</option>
          <option value="rental">Rentals</option>
        </SelectPill>}
      </div>
      {error ? (
        <StateBox tone="error" icon={AlertTriangle} title="Transactions couldn't be loaded" text={error.message}
          action={<PillButton icon={RefreshCw} onClick={reload} className="mt-2">Try again</PillButton>} />
      ) : !data ? (
        <div className="sl-stack">{[0, 1, 2].map((i) => <Skel key={i} h={46} r={10} className="block" />)}</div>
      ) : !data.results.length ? (
        <StateBox compact icon={ReceiptText} title="Nothing here for this period" />
      ) : (
        <div className="pl-tx" data-kind={refunds ? "refunds" : expenseRows ? "expenses" : "invoices"} aria-busy={loading}>
          <div className="pl-tx-row pl-tx-head" aria-hidden="true">
            {expenseRows ? (
              <><span>Expense</span><span>Category</span><span>Vendor</span><span className="pl-r">Amount</span><span className="pl-r">Counted</span></>
            ) : refunds ? (
              <><span>Invoice</span><span>Customer</span><span>Refunded on</span><span className="pl-r">Amount</span><span className="pl-r">Cost reversed</span></>
            ) : (
              <><span>Invoice</span><span>Customer</span><span>Source</span><span className="pl-r">Billed</span><span className="pl-r">Refunded</span><span className="pl-r">Revenue</span><span className="pl-r">Gross profit</span></>
            )}
          </div>
          {data.expenses_available === false && <p className="sl-note">Expense records aren't set up on this server yet.</p>}
          {data.results.map((r) => (expenseRows ? (
            <div key={r.id} className="pl-tx-row">
              <span className="pl-tx-main"><b>{r.code}</b><span className="pl-tx-sub">{fmtDay(r.date)} · {r.payment_status === "paid" ? "paid" : r.payment_status === "partial" ? "partly paid" : "unpaid"}{r.reference ? ` · ${r.reference}` : ""}</span></span>
              <span data-label="Category">{r.category}{r.classification === "other" ? " (other)" : ""}</span>
              <span data-label="Vendor" className="pl-wrap">{r.vendor || "—"}</span>
              <span data-label="Amount" className="pl-r pl-mono">{money(r.amount)}</span>
              <span data-label="Counted" className="pl-r pl-mono" title={r.gst_claimable ? `${money(r.gst_claimable)} claimable GST left out` : undefined}>{signed(-r.counted)}</span>
            </div>
          ) : refunds ? (
            <div key={r.id} className="pl-tx-row">
              <span className="pl-tx-main"><b>{r.code}</b><span className="pl-tx-sub">Invoice {fmtDay(r.invoice_date)} · {r.restocked ? "restocked" : "not restocked"}</span></span>
              <span data-label="Customer" className="pl-wrap">{r.party}</span>
              <span data-label="Refunded on">{fmtDay(r.refunded_on)} · {r.method}</span>
              <span data-label="Amount" className="pl-r pl-mono">{signed(-r.amount)}</span>
              <span data-label="Cost reversed" className="pl-r pl-mono">{r.cogs_reversed ? money(r.cogs_reversed) : "—"}</span>
            </div>
          ) : (
            <div key={r.id} className="pl-tx-row">
              <span className="pl-tx-main"><b>{r.code}</b><span className="pl-tx-sub">{fmtDay(r.date)} · {r.status}{r.is_advance ? " · advance" : ""}{r.cost_missing ? " · cost missing" : r.cost_estimated ? " · estimated cost" : ""}</span></span>
              <span data-label="Customer" className="pl-wrap">{r.party}</span>
              <span data-label="Source">{SOURCE_LABEL[r.source]}</span>
              <span data-label="Billed" className="pl-r pl-mono">{signed(r.billed)}</span>
              <span data-label="Refunded" className="pl-r pl-mono">{r.refunded ? signed(-r.refunded) : "—"}</span>
              <span data-label="Revenue" className="pl-r pl-mono">{kind === "settled" ? signed(r.revenue) : <span className="sl-empty">Not counted</span>}</span>
              <span data-label="Gross profit" className="pl-r pl-mono" data-tone={r.gross_profit === null ? undefined : tone(r.gross_profit)}>
                {r.gross_profit === null ? <span className="sl-empty" title="No goods cost on this bill (labour, rent, or parts without “Our cost”)">No goods cost</span> : signed(r.gross_profit)}
              </span>
            </div>
          )))}
        </div>
      )}
      {data && pages > 1 && (
        <div className="pl-pager">
          <button type="button" className="sl-icon-btn" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)} aria-label="Previous page"><ChevronLeft size={16} /></button>
          <span className="sl-note">Page {num(page)} of {num(pages)}</span>
          <button type="button" className="sl-icon-btn" disabled={page >= pages || loading} onClick={() => setPage((p) => p + 1)} aria-label="Next page"><ChevronRight size={16} /></button>
        </div>
      )}
    </Panel>
  );
}

function CmpRow({ r, total, currentId, onPick }) {
  return (
    <div className="pl-cmp-row" data-current={!total && r.store.id === currentId} data-total={total || undefined}>
      <span className="pl-tx-main">
        {total ? <b>All stores (consolidated)</b> : (
          <button type="button" className="sl-link-btn" onClick={() => onPick(r.store.id)} aria-label={`Open Profit & Loss for ${r.store.name}`}>{r.store.name}</button>
        )}
        {reliabilityOf(r.data_quality) !== "complete" && <span className="pl-tx-sub">{reliabilityOf(r.data_quality) === "estimated" ? "Some costs estimated" : "Some costs missing"}</span>}
      </span>
      <span data-label="Revenue" className="pl-r pl-mono">{signed(r.revenue)}</span>
      <span data-label="Cost of goods" className="pl-r pl-mono">{signed(r.cogs)}</span>
      <span data-label="Gross profit" className="pl-r pl-mono" data-tone={tone(r.gross_profit)}>{signed(r.gross_profit)}</span>
      <span data-label="Expenses" className="pl-r pl-mono">{signed(r.expenses)}</span>
      <span data-label="Net profit" className="pl-r pl-mono" data-tone={r.net_profit === null ? undefined : tone(r.net_profit)}>{signed(r.net_profit)}</span>
      <span data-label="Net margin" className="pl-r pl-mono">{pctText(r.net_margin_pct)}</span>
      <span data-label="Paid invoices" className="pl-r pl-mono">{num(r.transactions)}</span>
    </div>
  );
}

function Comparison({ period, currentId, onPick }) {
  const { data, error } = useFetch(`/reports/profit-loss/stores/?${query(null, period)}`);
  if (error) return null;
  if (!data) return <Skel h={180} r={13} className="block sl-span-2" />;
  if (!data.can_compare || data.stores.length < 2) return null;
  return (
    <Panel icon={Building2} title="Compare stores" className="sl-span-2" action={<span className="sl-note">{periodText(data.period)}</span>}>
      <div className="pl-cmp">
        <div className="pl-cmp-row pl-tx-head" aria-hidden="true">
          <span>Store</span><span className="pl-r">Revenue</span><span className="pl-r">Cost of goods</span><span className="pl-r">Gross profit</span><span className="pl-r">Expenses</span><span className="pl-r">Net profit</span><span className="pl-r">Net margin</span><span className="pl-r">Paid invoices</span>
        </div>
        {data.stores.map((r) => <CmpRow key={r.store.id} r={r} currentId={currentId} onPick={onPick} />)}
        {data.shared_expenses && (data.shared_expenses.operating_expenses + data.shared_expenses.other_expenses) > 0 && (
          <div className="pl-cmp-row" data-shared>
            <span className="pl-tx-main"><b>Shared / head office</b><span className="pl-tx-sub">Not assigned to any store</span></span>
            <span data-label="Expenses" className="pl-r pl-mono pl-cmp-shared">{signed(-(data.shared_expenses.operating_expenses + data.shared_expenses.other_expenses))}</span>
          </div>
        )}
        {data.consolidated && <CmpRow total r={data.consolidated} />}
      </div>
    </Panel>
  );
}

function Formulas() {
  return (
    <details className="pl-formulas sl-span-2">
      <summary><Scale size={14} aria-hidden="true" />How these figures are calculated</summary>
      <ul>
        <li><b>Revenue</b> = paid (and part- or fully-refunded) invoices dated in the period at this store, at their invoiced line prices, less refunds on those invoices. This is the same rule as Reports → Financial summary. Discounts are already in the invoiced prices. A repair advance and the final bill that deducts it count once.</li>
        <li><b>Not revenue:</b> unpaid invoices (shown as receivables), cancelled invoices, and the cash and bank book entries that mirror invoice payments.</li>
        <li><b>Cost of goods sold</b> = quantity × the product's cost price for every unit sold, less units returned and restocked. Units returned without restocking stay in cost. The CRM keeps only the <i>current</i> cost price, not the cost at the time of sale. Repairs and rentals have no recorded direct cost.</li>
        <li><b>Gross profit</b> = Revenue − Cost of goods sold. <b>Gross margin</b> = Gross profit ÷ Revenue.</li>
        <li><b>Expenses</b> = expenses recorded in Accounting → Expenses for this store, dated in the period, whether or not they've been paid. Claimable input GST is left out, and cancelled expenses aren't counted. Payments and their cash or bank book entries are never counted again. Shared / head-office expenses are never put on a store; they appear only in the all-store total.</li>
        <li><b>Net profit</b> = Gross profit − operating expenses − other expenses. <b>Net margin</b> = Net profit ÷ Revenue.</li>
        <li><b>Tax:</b> invoices store no tax component, so any GST collected is included in revenue.</li>
        <li>Dates are inclusive and use the server's configured time zone. Refunds count against the original invoice's date.</li>
      </ul>
    </details>
  );
}

/* ---------------------------------------------------------------- *
 * Dashboard
 * ---------------------------------------------------------------- */

export default function ProfitLoss({ store, stores, ownerView, onBack, onSwitchStore }) {
  // `period` is what the filter shows; `applied` is what the figures are for --
  // a custom range only applies once both dates are valid.
  const [period, setPeriod] = useState({ key: "this_month" });
  const [applied, setApplied] = useState(period);
  const changePeriod = (next) => {
    setPeriod(next);
    if (next.key !== "custom" || (!next.pending && next.from && next.to)) setApplied(next);
  };

  const path = `/reports/profit-loss/?${query(store.id, applied)}`;
  const { data, error, loading, reload } = useFetch(path);
  const shown = data && data.store.id === store.id ? data : null;
  const st = shown?.statement;
  const backRef = useRef(null);
  useEffect(() => { backRef.current?.focus(); }, [store.id]);

  const cards = useMemo(() => {
    if (!st) return null;
    const level = reliabilityOf(st.data_quality);
    const flag = level === "estimated" ? "Estimated" : level === "incomplete" ? "Incomplete" : null;
    return [
      { icon: TrendingUp, label: "Revenue", value: signed(st.revenue), tone: "blue",
        sub: `${money(st.billed)} billed · ${money(st.refunds)} refunded` },
      { icon: Package, label: "Cost of goods sold", value: signed(st.cogs), tone: "amber",
        sub: "Products and parts, at the cost locked when billed", flag },
      { icon: st.gross_profit < 0 ? TrendingDown : TrendingUp, label: st.gross_profit < 0 ? "Gross loss" : "Gross profit",
        value: signed(st.gross_profit), tone: tone(st.gross_profit), flag,
        sub: st.gross_profit < 0 ? "Cost of goods exceeded revenue" : "Revenue less cost of goods" },
      st.expenses === null
        ? { icon: Wallet, label: "Expenses", value: "Unavailable", tone: "grey", sub: EXPENSE_GAP[st.data_quality.expense_status] }
        : { icon: Wallet, label: "Expenses", value: signed(st.expenses), tone: "violet",
          sub: `${money(st.operating_expenses)} operating · ${money(st.other_expenses)} other` },
      st.net_profit === null
        ? { icon: Landmark, label: "Net profit / loss", value: "Unavailable", tone: "grey", sub: "Needs the period's expense records" }
        : { icon: Landmark, label: st.net_profit < 0 ? "Net loss" : "Net profit", value: signed(st.net_profit), tone: tone(st.net_profit),
          sub: "Gross profit less expenses", flag },
      { icon: Percent, label: "Net margin", value: pctText(st.net_margin_pct), tone: st.net_margin_pct === null ? "grey" : tone(Number(st.net_margin_pct)),
        sub: `Gross margin ${pctText(st.gross_margin_pct)} · ${plural(st.transactions, "paid invoice")}` },
    ];
  }, [st]);

  return (
    <div className="pl-page sl-stack">
      <div className="pl-top">
        <button ref={backRef} type="button" className="sl-link" onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Back to Store Locator</button>
        <div className="pl-top-actions">
          {stores.length > 1 && (
            <SelectPill label="Store" value={String(store.id)} onChange={(id) => onSwitchStore(Number(id))}>
              {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </SelectPill>
          )}
          <PillButton icon={RefreshCw} onClick={reload} disabled={loading}>{loading ? "Updating…" : "Refresh"}</PillButton>
        </div>
      </div>

      <header className="pl-head">
        <StoreMark sp={store} size="lg" />
        <div className="min-w-0">
          <p className="pl-eyebrow">Profit &amp; Loss</p>
          <h2 className="pl-title">{store.name}</h2>
          <div className="pl-meta">
            <KindBadge sp={store} />
            {ownerView ? <Badge tone="violet" icon={Building2}>All-store access</Badge> : <Badge tone="grey" icon={Lock}>Your store only</Badge>}
            {shown && <span><CalendarRange size={12} aria-hidden="true" />{periodText(shown.period)}</span>}
            {shown && <span><RefreshCw size={12} aria-hidden="true" />Updated {stampText(shown.generated_at, shown.timezone)}</span>}
          </div>
        </div>
      </header>

      <PeriodBar period={period} current={shown?.period} onChange={changePeriod} />

      {error ? (
        error.status === 403 ? (
          <StateBox icon={Lock} title="Profit & Loss isn't available for this store" text={error.message} />
        ) : (
          <StateBox tone="error" icon={AlertTriangle} title="Profit & Loss couldn't be loaded" text={error.message}
            action={<PillButton icon={RefreshCw} onClick={reload} className="mt-2">Try again</PillButton>} />
        )
      ) : (
        <>
          <div className="pl-cards" aria-busy={!st}>
            {cards ? cards.map((c) => <MetricCard key={c.label} {...c} />) : [0, 1, 2, 3, 4, 5].map((i) => <MetricCard key={i} icon={Coins} loading label="" />)}
          </div>
          {st && <DataQuality st={st} period={shown.period} />}
          {st ? (
            <div className="sl-overview">
              <RevenueVsCosts trend={shown.trend} />
              <ProfitTrend trend={shown.trend} />
              <div className="sl-span-2"><MonthlyPerformance monthly={shown.monthly} /></div>
              <SourceMix st={st} />
              <Panel icon={Scale} title="At a glance">
                <dl className="sl-kv">
                  <div><dt>Paid invoices</dt><dd>{num(st.transactions)}</dd></div>
                  <div><dt>Refunds</dt><dd>{num(st.refund_count)} · {money(st.refunds)}</dd></div>
                  <div><dt>Unpaid (not revenue)</dt><dd>{num(st.receivables.count)} · {money(st.receivables.amount)}</dd></div>
                  <div><dt>Cancelled (excluded)</dt><dd>{num(st.cancelled.count)} · {money(st.cancelled.amount)}</dd></div>
                  <div className="sl-kv-wide"><dt>Average paid invoice</dt><dd>{st.transactions ? money(Math.round(st.revenue / st.transactions)) : "—"}</dd></div>
                </dl>
              </Panel>
              <Statement st={st} />
              {ownerView && <Comparison period={applied} currentId={store.id} onPick={onSwitchStore} />}
              <Transactions key={`${store.id}:${query(null, applied)}`} storeId={store.id} period={applied} />
              <Formulas />
            </div>
          ) : (
            <div className="sl-overview">{[0, 1].map((i) => <Skel key={i} h={300} r={13} className="block" />)}</div>
          )}
        </>
      )}
    </div>
  );
}
