import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowUpRight, Ban, Boxes, Building2, CalendarClock, CalendarDays, CircleCheck, Clock3, History,
  KeyRound, MapPin, MessageSquare, Phone, Receipt, RefreshCw, Repeat2, ShieldCheck, Store, UserCog, Wallet, Wrench,
} from "lucide-react";
import { api } from "../../lib/api";
import { SearchInput } from "../../components/Atoms";
import { Alert, Dialog } from "../settings/StaffUi";
import { Badge, Skel, StateBox } from "./shared";
import { initials, num, oneLine, personName } from "./format";
import "../settings/staff.css";

/*
 * Staff Activity Logs -- one account's completed work, oldest first
 * (Store Locator -> Staff list -> Logs, or My activity).
 *
 * Everything comes from GET /users/<id>/activity/. The backend decides who
 * may open whose timeline and which entries each viewer sees, before any
 * count, filter, search or page (accounts.activity): Superusers see Admins,
 * Staff and themselves; Admins see Staff and themselves; Staff only their
 * own work at their own store. This dialog only lays out what comes back --
 * the account picker lists only accounts the backend marked viewable, and
 * every switch is a fresh, re-checked request. Nothing is reconstructed:
 * entries exist only for work the CRM actually recorded.
 */

const MODULE_ICON = {
  sales: Receipt, payments: Wallet, rentals: Repeat2, repairs: Wrench, inventory: Boxes, parties: MessageSquare,
  accounting: Wallet, warranty: ShieldCheck, broadcast: MessageSquare, stores: Building2, staff: UserCog,
};
// Pages an entry can open (new tab, so this dialog stays open). Only
// customers have per-record URLs; everything else opens its module.
const MODULE_ROUTE = {
  sales: "/sales", payments: "/sales", rentals: "/rentals", repairs: "/repairs", inventory: "/inventory",
  parties: "/parties", accounting: "/accounting", warranty: "/warranty", broadcast: "/broadcast",
  stores: "/store-locator", staff: "/settings",
};
const PERIODS = [
  { id: "today", label: "Today" }, { id: "yesterday", label: "Yesterday" }, { id: "week", label: "This week" },
  { id: "month", label: "This month" }, { id: "day", label: "Custom date" }, { id: "range", label: "Date range" },
  { id: "all", label: "All time" },
];
const KINDS = [
  { id: "", label: "All actions" }, { id: "created", label: "Created" }, { id: "updated", label: "Updated" },
  { id: "deleted", label: "Deleted" }, { id: "other", label: "Lifecycle actions" },
];
const DEFAULT_FILTERS = { period: "today", day: "", from: "", to: "", q: "", module: "", kind: "", store: "" };

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

// Formatters in the CRM's configured timezone (sent by the API), so a day
// here is the same whole day the backend filtered on.
function useFormats(tz) {
  return useMemo(() => {
    const opt = tz ? { timeZone: tz } : {};
    const make = (o) => { try { return new Intl.DateTimeFormat("en-IN", { ...o, ...opt }); } catch { return new Intl.DateTimeFormat("en-IN", o); } };
    const date = make({ day: "2-digit", month: "short", year: "numeric" });
    const time = make({ hour: "2-digit", minute: "2-digit" });
    const day = make({ weekday: "short", day: "2-digit", month: "short", year: "numeric" });
    return {
      date: (iso) => (iso ? date.format(new Date(iso)) : "—"),
      time: (iso) => (iso ? time.format(new Date(iso)) : "—"),
      stamp: (iso) => (iso ? `${date.format(new Date(iso))}, ${time.format(new Date(iso))}` : "—"),
      // a YYYY-MM-DD calendar day (no time) -- format it as that day, in UTC, so it never shifts
      calendar: (ymd) => (ymd ? new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${ymd}T00:00:00Z`)) : ""),
      dayOf: day,
    };
  }, [tz]);
}

function recordLink(e) {
  if (e.record_type === "parties.party" && e.record_id && e.action !== "deleted") return `/parties/${e.record_id}`;
  return MODULE_ROUTE[e.module] || null;
}

function Identity({ staff, fallback }) {
  const s = staff || fallback;
  const name = s.name || personName(s);
  return (
    <div className="sl-logs-id">
      <span className="sl-avatar" data-size="lg" aria-hidden="true">{initials(name)}</span>
      <div className="min-w-0">
        <p className="sl-logs-name">{name}{staff?.is_self && <span className="sl-logs-you">You</span>}</p>
        <p className="sl-logs-meta"><span className="sl-mono">@{s.username}</span><span aria-hidden="true">·</span><span>Staff ID {s.id}</span></p>
      </div>
    </div>
  );
}

function StoreLine({ staff }) {
  if (!staff) return null;
  return (
    <div className="sl-logs-tags">
      <Badge tone="violet" icon={UserCog}>{staff.role || "No role"}</Badge>
      <Badge tone={staff.is_active ? "green" : "grey"} icon={staff.is_active ? CircleCheck : Ban}>{staff.is_active ? "Active account" : "Deactivated"}</Badge>
      {staff.sees_all_stores ? <Badge icon={Building2}>All stores</Badge>
        : staff.store ? <Badge icon={Store}>{staff.store.name}</Badge>
          : <Badge tone="amber" icon={Store}>No Store Location</Badge>}
      {staff.store?.address && <span className="sl-logs-addr"><MapPin size={12} aria-hidden="true" />{oneLine(staff.store.address)}</span>}
      {staff.store?.phone && <span className="sl-logs-addr"><Phone size={12} aria-hidden="true" />{staff.store.phone}</span>}
    </div>
  );
}

function Changes({ changes }) {
  const rows = Object.entries(changes || {});
  if (!rows.length) return null;
  return (
    <dl className="sl-logs-changes">
      {rows.map(([field, [before, after]]) => (
        <div key={field}>
          <dt>{field.replace(/_/g, " ")}</dt>
          <dd>
            {before === "(changed)" ? <em>changed (value not stored)</em> : (
              <><span className="sl-logs-before">{before === null || before === "" ? "—" : String(before)}</span>
                <span aria-hidden="true"> → </span><span className="sr-only">to</span>
                <span className="sl-logs-after">{after === null || after === "" ? "—" : String(after)}</span></>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Card({ e, f }) {
  const Icon = MODULE_ICON[e.module] || History;
  const link = recordLink(e);
  return (
    <li className="sl-logs-card2" aria-label={`Activity number ${e.seq}: ${e.description}`}>
      <div className="sl-logs-card2-head">
        <span className="sl-logs-seq" aria-hidden="true">#{e.seq}</span>
        <span className="sl-logs-dot" data-module={e.module} aria-hidden="true"><Icon size={13} /></span>
        <p className="sl-logs-desc">{e.description}</p>
      </div>
      <dl className="sl-logs-facts">
        {e.record_label && (
          <div><dt>{e.record_kind || "Record"}</dt><dd>
            {link ? (
              <a className="sl-logs-ref" href={link} target="_blank" rel="noopener noreferrer" aria-label={`Open ${e.module_label} (${e.record_label}) in a new tab`}>
                {e.record_label}<ArrowUpRight size={12} aria-hidden="true" />
              </a>
            ) : <span className="sl-logs-ref" data-static="true">{e.record_label}</span>}
          </dd></div>
        )}
        <div><dt>Module</dt><dd>{e.module_label}</dd></div>
        <div><dt>Date</dt><dd><time dateTime={e.at}>{f.date(e.at)}</time></dd></div>
        <div><dt>Time</dt><dd><time dateTime={e.at}>{f.time(e.at)}</time></dd></div>
        <div><dt>Store</dt><dd>{e.store ? e.store.name : <span className="sl-logs-muted">Not associated with a store</span>}</dd></div>
      </dl>
      {e.source === "imported" && <p className="sl-logs-earlier"><History size={12} aria-hidden="true" />Earlier record — copied from the repair / rental history</p>}
      <Changes changes={e.changes} />
    </li>
  );
}

function rangeText(data, filters, f) {
  const r = data?.range;
  if (!r) return "";
  const label = PERIODS.find((p) => p.id === filters.period)?.label;
  if (!r.from && !r.to) return "All recorded time";
  if (r.from && r.to && r.from === r.to) return `${label && filters.period !== "day" && filters.period !== "range" ? `${label} · ` : ""}${f.calendar(r.from)}`;
  const span = `${r.from ? f.calendar(r.from) : "Beginning"} – ${r.to ? f.calendar(r.to) : "today"}`;
  return label && !["day", "range"].includes(filters.period) ? `${label} · ${span}` : span;
}

export default function StaffLogsDialog({ user, candidates = [], onClose }) {
  const [target, setTarget] = useState(user);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const q = useDebounced(filters.q);
  const [state, setState] = useState({ data: null, items: [], next: null, loading: true, more: false, error: null });
  const seq = useRef(0);
  const f = useFormats(state.data?.timezone);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (["today", "yesterday", "week", "month"].includes(filters.period)) p.set("period", filters.period);
    if (filters.period === "day" && filters.day) { p.set("date_from", filters.day); p.set("date_to", filters.day); }
    if (filters.period === "range") {
      if (filters.from) p.set("date_from", filters.from);
      if (filters.to) p.set("date_to", filters.to);
    }
    if (q.trim()) p.set("q", q.trim());
    if (filters.module) p.set("module", filters.module);
    if (filters.kind) p.set("kind", filters.kind);
    if (filters.store) p.set("store", filters.store);
    return p.toString();
  }, [filters.period, filters.day, filters.from, filters.to, q, filters.module, filters.kind, filters.store]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api.get(`/users/${target.id}/activity/${query ? `?${query}` : ""}`);
      if (mine === seq.current) setState({ data, items: data.results, next: data.next, loading: false, more: false, error: null });
    } catch (error) {
      if (mine === seq.current) setState((s) => ({ ...s, data: s.data?.staff?.id === target.id ? s.data : null, loading: false, error }));
    }
  }, [target.id, query]);

  useEffect(() => { load(); }, [load]);

  // keep keyboard focus inside the dialog when the control that had it
  // (e.g. "Try again") unmounts as the timeline arrives
  const loaded = !!state.data;
  useEffect(() => {
    if (loaded && (document.activeElement === document.body || !document.activeElement)) {
      document.querySelector(".sl-logs-tools input")?.focus();
    }
  }, [loaded]);

  const loadMore = async () => {
    if (!state.next) return;
    const mine = seq.current;
    setState((s) => ({ ...s, more: true, error: null }));
    try {
      const url = new URL(state.next);
      const data = await api.get(`${url.pathname.replace(/^\/api/, "")}${url.search}`);
      if (mine === seq.current) setState((s) => ({ ...s, items: [...s.items, ...data.results], next: data.next, more: false }));
    } catch (error) {
      if (mine === seq.current) setState((s) => ({ ...s, more: false, error }));
    }
  };

  const set = (k) => (v) => setFilters((x) => ({ ...x, [k]: v }));
  const switchTarget = (id) => {
    const next = candidates.find((c) => String(c.id) === String(id));
    if (!next || next.id === target.id) return;
    setState({ data: null, items: [], next: null, loading: true, more: false, error: null });
    setFilters((x) => ({ ...x, store: "" }));
    setTarget(next);
  };

  const { data, items } = state;
  const narrowed = !!(filters.q || filters.module || filters.kind || filters.store);
  const changed = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);
  const singleDay = data?.range?.from && data.range.from === data.range.to;
  const hidden = state.error && [403, 404].includes(state.error.status);
  const isSelf = data?.staff?.is_self ?? (candidates.length === 0);

  let body;
  if (hidden && !data) {
    body = <StateBox icon={KeyRound} title="This activity log isn't available to your account"
      text="Superusers and administrators can review staff work within their reach; everyone else sees only their own activity." />;
  } else if (state.error && !data) {
    body = (
      <StateBox tone="error" icon={AlertTriangle} title="Couldn't load the activity log"
        text={state.error.message || "The server didn't respond. Check your connection and try again."}
        action={<button type="button" className="st-btn mt-2" onClick={load}><RefreshCw size={14} aria-hidden="true" />Try again</button>} />
    );
  } else if (!data) {
    body = (
      <div className="sl-logs-loading" aria-busy="true" aria-label="Loading activity">
        <div className="sl-logs-sum">{[0, 1, 2, 3, 4].map((i) => <Skel key={i} h={60} r={12} className="block" />)}</div>
        {[0, 1, 2].map((i) => <Skel key={i} h={96} r={12} className="block" />)}
      </div>
    );
  } else {
    const { summary } = data;
    const cards = [
      { label: "Recorded work", value: num(summary.total), icon: History },
      { label: "Last 7 days", value: num(summary.last_7_days), icon: CalendarClock },
      { label: "Last 30 days", value: num(summary.last_30_days), icon: CalendarClock },
      { label: "Latest activity", value: summary.latest_at ? f.stamp(summary.latest_at) : "None yet", icon: Clock3, small: true },
      { label: "Last sign-in", value: data.staff.last_login ? f.stamp(data.staff.last_login) : "Not recorded", icon: KeyRound, small: true },
    ];
    body = (
      <div className="sl-logs">
        <div className="sl-logs-top">
          <section className="sl-logs-sum" aria-label="Activity summary">
            {cards.map((c) => (
              <div key={c.label} className="sl-logs-card">
                <c.icon size={14} aria-hidden="true" />
                <span className="sl-logs-card-value" data-small={c.small || undefined}>{c.value}</span>
                <span className="sl-logs-card-label">{c.label}</span>
              </div>
            ))}
          </section>

          <div className="sl-logs-periods" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.id} type="button" aria-pressed={filters.period === p.id} onClick={() => set("period")(p.id)}>{p.label}</button>
            ))}
          </div>

          <div className="sl-logs-tools" role="search" aria-label="Filter activity">
            {filters.period === "day" && (
              <label className="st-select">Date<input type="date" value={filters.day} onChange={(e) => set("day")(e.target.value)} /></label>
            )}
            {filters.period === "range" && (
              <>
                <label className="st-select">From<input type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => set("from")(e.target.value)} /></label>
                <label className="st-select">To<input type="date" value={filters.to} min={filters.from || undefined} onChange={(e) => set("to")(e.target.value)} /></label>
              </>
            )}
            <SearchInput value={filters.q} onChange={(e) => set("q")(e.target.value)} onClear={() => set("q")("")}
              placeholder="Search work or references (e.g. INV-1024)" ariaLabel="Search activity" />
            <label className="st-select">Module
              <select value={filters.module} onChange={(e) => set("module")(e.target.value)}>
                <option value="">All modules</option>
                {data.modules.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
            <label className="st-select">Action
              <select value={filters.kind} onChange={(e) => set("kind")(e.target.value)}>
                {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
            </label>
            {summary.by_store.length > 1 && (
              <label className="st-select">Store
                <select value={filters.store} onChange={(e) => set("store")(e.target.value)}>
                  <option value="">All stores</option>
                  {summary.by_store.map((s) => <option key={s.id ?? "none"} value={s.id ?? "none"}>{s.name || "Not associated"}</option>)}
                </select>
              </label>
            )}
            {changed && <button type="button" className="st-btn" onClick={() => setFilters(DEFAULT_FILTERS)}>Clear filters</button>}
          </div>

          <p className="sl-logs-status" aria-live="polite">
            <CalendarDays size={14} aria-hidden="true" />
            <span><b>{rangeText(data, filters, f)}</b></span>
            <span aria-hidden="true">·</span>
            <span>{state.loading ? "Updating…" : `${num(data.count)} ${data.count === 1 ? "activity" : "activities"}${narrowed ? " match" : ""}`}</span>
            <span className="sl-logs-tz">Times in {data.timezone}</span>
          </p>
          {state.error && <Alert>{state.error.message || "Couldn't refresh the activity."} <button type="button" className="sl-inline-btn" onClick={load}>Retry</button></Alert>}
        </div>

        <div className="sl-logs-scroll" tabIndex={0} aria-label="Activity timeline" aria-busy={state.loading}>
          {items.length ? (
            <>
              <ol className="sl-logs-cards">{items.map((e) => <Card key={e.id} e={e} f={f} />)}</ol>
              {state.next && (
                <button type="button" className="st-btn sl-logs-more" onClick={loadMore} disabled={state.more}>
                  {state.more ? "Loading…" : `Load later activity (${num(data.count - items.length)} more)`}
                </button>
              )}
              <p className="sl-note sl-logs-foot">
                Numbers count this person&apos;s whole recorded timeline (#1 = earliest){narrowed || data.range.filtered ? " — gaps are work outside these filters" : ""}.
                Only work the CRM recorded{summary.tracking_since ? ` since ${f.date(summary.tracking_since)}` : ""} appears; earlier work can&apos;t be reconstructed.
              </p>
            </>
          ) : (
            <StateBox icon={History}
              title={narrowed ? "No activity matches these filters" : singleDay ? "No work activity recorded for this date" : "No work activity recorded for this period"}
              text={narrowed ? "Change or clear the search and filters." : summary.total ? "Pick another day or period to see this person's recorded work." : "Work appears here once it's completed in the CRM."} />
          )}
        </div>
      </div>
    );
  }

  const name = data?.staff?.name || personName(target);
  return (
    <Dialog size="wide" labelledBy="sl-logs-title" onClose={onClose}
      title={<>{isSelf ? "My activity" : "Activity logs"}<span className="sr-only"> — {name}</span></>}
      subtitle={(
        <div className="sl-logs-head">
          <div className="sl-logs-head-row">
            <Identity staff={data?.staff} fallback={target} />
            {candidates.length > 1 && (
              <label className="st-select sl-logs-picker">Viewing
                <select value={String(target.id)} onChange={(e) => switchTarget(e.target.value)} aria-label="Choose whose activity to view">
                  {candidates.map((c) => <option key={c.id} value={String(c.id)}>{personName(c)}{c.role_label ? ` · ${c.role_label}` : ""}</option>)}
                </select>
              </label>
            )}
          </div>
          <StoreLine staff={data?.staff} />
        </div>
      )}
      footer={<button type="button" className="st-btn" onClick={onClose}>Close</button>}
    >
      {body}
    </Dialog>
  );
}
