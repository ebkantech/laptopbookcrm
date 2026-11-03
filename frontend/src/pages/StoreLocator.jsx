import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowRight, Building2, CircleCheck, CircleOff, Eye, History, KeyRound, Lock, MapPin, Pencil, Plus, RefreshCw, Store, TrendingUp, Users, Warehouse,
} from "lucide-react";
import { api } from "../lib/api";
import { announceStoreChanged, onStoreChanged } from "../lib/storeEvents";
import { useSession } from "../context/SessionContext";
import PageHeader from "../components/PageHeader";
import { PillButton, SearchInput } from "../components/Atoms";
import InventoryView from "./storeLocator/InventoryView";
import { RolesView, StaffView } from "./storeLocator/PeopleViews";
import { StoreDrawer } from "./storeLocator/StoreDetail";
import StoreForm from "./storeLocator/StoreForm";
import StoreStatusDialog from "./storeLocator/StoreStatusDialog";
import StaffLogsDialog from "./storeLocator/StaffLogsDialog";
import ProfitLoss from "./storeLocator/ProfitLoss";
import { Alert } from "./settings/StaffUi";
import { useStoreDetail } from "./storeLocator/useStoreDetail";
import { Badge, KindBadge, SelectPill, Segmented, Skel, StateBox, StatusBadge, StoreMark } from "./storeLocator/shared";
import { PENDING_MESSAGE, isShop, num, oneLine, plural } from "./storeLocator/format";
import "./StoreLocator.css";

/*
 * Store & Channel Management (route /store-locator).
 *
 * Every figure comes from existing APIs, which the backend scopes to the
 * requesting account (accounts.store_scope): the Owner / Super Admin sees
 * every shop and channel, store staff only their own store, and unassigned
 * staff nothing at all -- the UI only arranges what the API returns.
 *
 *   GET /stock-points/            shops & online channels (Total Channels)
 *   GET /stock-points/summary/    per-point units, records, low / out, staff
 *   GET /stock-points/inventory/  stock per variant & part per point
 *   GET /stock-points/<id>/locator/  one point's detail (drawer)
 *   GET /users/                   staff and their Store Location
 *   GET /roles/                   role records (Total Roles)
 *   POST /stock-points/, PATCH /stock-points/<id>/   Owner only: add / edit
 *
 *   POST /stock-points/<id>/set-status/   Superuser / administrators: activate, deactivate
 *   GET /reports/profit-loss/...          Profit & Loss (storeLocator/ProfitLoss.jsx): Superuser and
 *                                         authorised Admins only (me.can_view_profit_loss)
 *
 * An edit updates the same StockPoint row, so every record linked to it by
 * id shows the new details. After a save this page refetches, and
 * lib/storeEvents tells the rest of the app (and other open tabs) to.
 *
 * Active / Inactive (catalog.status) is administrator information: the API
 * only sends is_active to them (me.can_manage_store_status), and only they
 * get the Active / Inactive cards, status badges and controls. Inactive
 * stock points stay listed here; only NEW operations there are blocked.
 */

const VIEWS = [
  { id: "channels", label: "Channels", icon: Building2 },
  { id: "staff", label: "Staff", icon: Users },
  { id: "roles", label: "Roles", icon: KeyRound },
  { id: "inventory", label: "Inventory", icon: Warehouse },
];

/* ---------------------------------------------------------------- *
 * Summary cards
 * ---------------------------------------------------------------- */

function SummaryCard({ id, icon: Icon, tone, label, value, sub, view, onSelect, loading, pressed }) {
  const selected = pressed ?? view === id;
  return (
    <button type="button" className="sl-sum" data-tone={tone} aria-pressed={selected} onClick={() => onSelect(id)}
      aria-label={`${label}: ${typeof value === "number" ? value : value || "loading"}. Show details`}>
      <span className="sl-sum-icon"><Icon size={19} aria-hidden="true" /></span>
      {loading ? (
        <><Skel w="38%" h={28} className="mt-3 block" /><Skel w="60%" h={11} className="mt-2 block" /></>
      ) : (
        <>
          <span className="sl-sum-value" data-muted={typeof value !== "number"}>{typeof value === "number" ? num(value) : value}</span>
          <span className="sl-sum-label">{label}</span>
          {sub && <span className="sl-sum-sub">{sub}</span>}
        </>
      )}
      <span className="sl-sum-go" aria-hidden="true">View <ArrowRight size={12} /></span>
    </button>
  );
}

/* ---------------------------------------------------------------- *
 * Channel table
 * ---------------------------------------------------------------- */

const STATUS_FILTER_LABEL = { active: "active", inactive: "inactive" };

function ChannelsView({ points, counts, countsFailed, selectedId, onOpen, onOpenInventory, onEdit, onProfitLoss, ownerView, showStatus, statusFilter = "all", onStatusFilter }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [invFilter, setInvFilter] = useState("all");
  const [sort, setSort] = useState("name");

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const c = (sp, k) => counts?.[sp.id]?.[k] ?? -1;
    const list = points.filter((sp) => {
      if (statusFilter === "active" && sp.is_active === false) return false;
      if (statusFilter === "inactive" && sp.is_active !== false) return false;
      if (kind !== "all" && sp.kind !== kind) return false;
      if (invFilter === "out" && !(c(sp, "out_of_stock") > 0)) return false;
      if (invFilter === "low" && !(c(sp, "low_stock") > 0)) return false;
      if (invFilter === "empty" && c(sp, "stock_records") !== 0) return false;
      if (!needle) return true;
      return [sp.name, sp.slug, sp.address].some((v) => (v || "").toLowerCase().includes(needle));
    });
    const by = {
      name: (a, b) => a.name.localeCompare(b.name),
      units: (a, b) => c(b, "product_units") - c(a, "product_units") || a.name.localeCompare(b.name),
      out: (a, b) => c(b, "out_of_stock") - c(a, "out_of_stock") || a.name.localeCompare(b.name),
      staff: (a, b) => c(b, "staff_count") - c(a, "staff_count") || a.name.localeCompare(b.name),
    }[sort];
    return [...list].sort(by);
  }, [points, counts, query, kind, invFilter, sort, statusFilter]);

  const shops = points.filter(isShop).length;
  const metric = (sp, k) => (counts ? num(counts[sp.id]?.[k]) : "—");

  return (
    <div className="sl-stack">
      <div className="sl-tools">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} onClear={() => setQuery("")} placeholder="Search store or channel name, code or address" />
        {ownerView && points.length > 1 && (
          <Segmented label="Type" value={kind} onChange={setKind} options={[
            { id: "all", label: "All", count: points.length },
            { id: "shop", label: "Physical shops", count: shops },
            { id: "online", label: "Online channels", count: points.length - shops },
          ]} />
        )}
        <SelectPill label="Inventory" value={invFilter} onChange={setInvFilter} disabled={!counts}>
          <option value="all">All</option>
          <option value="out">Has out-of-stock</option>
          <option value="low">Has low stock</option>
          <option value="empty">No stock records</option>
        </SelectPill>
        <SelectPill label="Sort" value={sort} onChange={setSort}>
          <option value="name">Name A–Z</option>
          <option value="units" disabled={!counts}>Most units</option>
          <option value="out" disabled={!counts}>Most out of stock</option>
          <option value="staff" disabled={!counts}>Most staff</option>
        </SelectPill>
      </div>
      <p className="sl-note" aria-live="polite">
        Showing {num(shown.length)} of {plural(points.length, "stock point")}
        {showStatus && statusFilter !== "all" && (
          <> · {STATUS_FILTER_LABEL[statusFilter]} only · <button type="button" className="sl-inline-btn" onClick={() => onStatusFilter("all")}>Show all</button></>
        )}
        {countsFailed && " · inventory and staff totals couldn't be loaded"}
      </p>

      {shown.length ? (
        <div className="sl-table" role="table" aria-label="Stores and channels" data-editable={!!onEdit} data-pl={!!onProfitLoss}>
          <div className="sl-tr sl-th sl-tr-ch" role="row">
            <span role="columnheader">Channel / store</span>
            <span role="columnheader">Type</span>
            <span role="columnheader">Store location</span>
            <span role="columnheader" className="sl-num">Staff</span>
            <span role="columnheader" className="sl-num">Product units</span>
            <span role="columnheader" className="sl-num">Out of stock</span>
            <span role="columnheader" className="sl-act">Actions</span>
          </div>
          {shown.map((sp) => {
            const out = counts?.[sp.id]?.out_of_stock;
            return (
              <div key={sp.id} className="sl-tr sl-tr-ch" role="row" data-selected={selectedId === sp.id}
                data-inactive={showStatus && sp.is_active === false}>
                <span role="cell" className="sl-td-main">
                  <StoreMark sp={sp} size="sm" />
                  <span className="min-w-0">
                    <span className="sl-row-name" title={sp.name}>{sp.name}</span>
                    <span className="sl-row-sub" title={sp.slug}>{sp.slug}</span>
                    {showStatus && <span className="sl-row-status"><StatusBadge sp={sp} /></span>}
                  </span>
                </span>
                <span role="cell" data-label="Type"><KindBadge sp={sp} /></span>
                <span role="cell" data-label="Store location" className="sl-td-loc">
                  {sp.address ? (
                    <span className="sl-wrap" title={oneLine(sp.address)}><MapPin size={12} aria-hidden="true" className="sl-ico" />{oneLine(sp.address)}</span>
                  ) : isShop(sp) ? (
                    <span className="sl-empty">Address not configured</span>
                  ) : (
                    <span className="sl-empty">Online channel — no physical location</span>
                  )}
                </span>
                <span role="cell" className="sl-num" data-label="Staff">{isShop(sp) ? metric(sp, "staff_count") : <span className="sl-empty" title="Online channels aren't staff locations">n/a</span>}</span>
                <span role="cell" className="sl-num" data-label="Product units">
                  {counts ? (
                    <button type="button" className="sl-count-btn" data-tone="grey" onClick={() => onOpenInventory(sp.id, "all")}
                      aria-label={`${metric(sp, "product_units")} product units at ${sp.name} — open inventory`}>{metric(sp, "product_units")}</button>
                  ) : "—"}
                </span>
                <span role="cell" className="sl-num" data-label="Out of stock">
                  {!counts ? "—" : out ? (
                    <button type="button" className="sl-count-btn" data-tone="red" onClick={() => onOpenInventory(sp.id, "out")}
                      aria-label={`${num(out)} out-of-stock records at ${sp.name} — open inventory`}>{num(out)}</button>
                  ) : <span className="sl-count-zero">0</span>}
                </span>
                <span role="cell" className="sl-act">
                  <span className="sl-act-btns">
                    <button type="button" className="sl-view-btn" onClick={(e) => onOpen(sp, e.currentTarget)} aria-haspopup="dialog"
                      aria-label={`View details of ${sp.name}`} title="View details">
                      <Eye size={14} aria-hidden="true" /><span className="sl-act-label">View details</span>
                    </button>
                    {onEdit && (
                      <button type="button" className="sl-view-btn" onClick={() => onEdit(sp)} aria-haspopup="dialog" aria-label={`Edit ${sp.name}`} title="Edit store">
                        <Pencil size={14} aria-hidden="true" /><span className="sl-act-label">Edit</span>
                      </button>
                    )}
                    {onProfitLoss && (
                      <button type="button" className="sl-view-btn" data-pl="true" onClick={() => onProfitLoss(sp)}
                        aria-label={`Profit & Loss for ${sp.name}`} title="Profit & Loss">
                        <TrendingUp size={14} aria-hidden="true" /><span className="sl-act-label">P&amp;L</span>
                      </button>
                    )}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <StateBox title="No stores or channels match" text="Change the search or filters." />
      )}
      <p className="sl-note">
        {showStatus && "Inactive shops and channels stay listed (dimmed) with all their history; no new operations can be recorded there. "}
        Out of stock counts stock records at 0 units — variants never stocked at a location aren't counted as zero.
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------- *
 * Page
 * ---------------------------------------------------------------- */

// Replace a stock point by id (or add a new one), keeping the API's name order.
function upsertPoint(points, store) {
  const rest = points.filter((p) => p.id !== store.id);
  return [...rest, { ...points.find((p) => p.id === store.id), ...store }].sort((a, b) => a.name.localeCompare(b.name));
}

function Management({ me }) {
  const ownerView = !!me.sees_all_stores;
  // store create / edit is Owner / Super Admin only -- the backend enforces it
  const canManageStores = ownerView;
  // Active / Inactive: Superuser and administrators only (backend: catalog.status)
  const canManageStatus = !!me.can_manage_store_status;
  const [form, setForm] = useState(null); // { store } -- store is null for a new one
  const [statusFor, setStatusFor] = useState(null); // the store whose status dialog is open
  // Staff Activity Logs (backend: accounts.activity): everyone may open their own
  // work timeline; only Superusers / Admins may open others' (and pick whose)
  const canViewOwnLogs = !!me.can_view_own_activity;
  const canViewOthersLogs = !!me.can_view_staff_logs;
  const [logsFor, setLogsFor] = useState(null); // the staff member whose logs dialog is open
  const [statusFilter, setStatusFilter] = useState("all");
  const [flash, setFlash] = useState("");
  const [data, setData] = useState({ points: null, counts: null, users: null, roles: null });
  const [errors, setErrors] = useState({});
  const [refreshing, setRefreshing] = useState(true);
  const [view, setView] = useState("channels");
  const [inv, setInv] = useState({ data: null, error: null, loading: false });
  const [focus, setFocus] = useState({ mode: "channel", storeId: null, level: "all" });
  const [selected, setSelected] = useState(null);
  // Profit & Loss (backend: reports.profit_loss) -- Superuser and authorised Admins only
  const canViewPL = !!me.can_view_profit_loss;
  const [plStoreId, setPlStoreId] = useState(null);
  const scrollRef = useRef(null);
  const savedScroll = useRef(0);
  const detail = useStoreDetail();
  const alive = useRef(true);
  const seq = useRef(0);
  const invSeq = useRef(0);
  const opener = useRef(null);

  const fetchAll = useCallback(async () => {
    const mine = ++seq.current;
    const [points, summary, users, roles] = await Promise.allSettled([
      api.getAll("/stock-points/"), api.get("/stock-points/summary/"), api.getAll("/users/"), api.getAll("/roles/"),
    ]);
    if (!alive.current || mine !== seq.current) return;
    const ok = (r) => (r.status === "fulfilled" ? r.value : null);
    setData({
      points: ok(points),
      counts: Array.isArray(ok(summary)) ? Object.fromEntries(ok(summary).map((r) => [r.id, r])) : null,
      users: ok(users),
      roles: ok(roles),
    });
    setErrors({
      points: points.status === "rejected" ? points.reason : null,
      counts: summary.status === "rejected",
      users: users.status === "rejected" ? users.reason : null,
      roles: roles.status === "rejected" ? roles.reason : null,
    });
    setRefreshing(false);
  }, []);

  const fetchInventory = useCallback(async () => {
    const mine = ++invSeq.current;
    setInv((s) => ({ ...s, error: null, loading: true }));
    try {
      const payload = await api.get("/stock-points/inventory/");
      if (alive.current && mine === invSeq.current) setInv({ data: payload, error: null, loading: false });
    } catch (error) {
      if (alive.current && mine === invSeq.current) setInv({ data: null, error, loading: false });
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    fetchAll();
    return () => { alive.current = false; };
  }, [fetchAll]);

  const refresh = () => {
    setRefreshing(true);
    detail.clear();
    fetchAll();
    if (inv.data || inv.error) fetchInventory();
  };

  // A store was added or edited -- here or in another tab. Show its new
  // details at once, then refetch everything that names stores.
  const { clear: clearDetail, load: loadDetail, patchStore } = detail;
  const selectedId = useRef(null);
  const invLoaded = useRef(false);
  useEffect(() => {
    selectedId.current = selected?.id ?? null;
    invLoaded.current = !!(inv.data || inv.error);
  });
  useEffect(() => onStoreChanged(({ store }) => {
    if (store?.id) {
      setData((d) => (d.points ? { ...d, points: upsertPoint(d.points, store) } : d));
      patchStore(store);
    }
    clearDetail();
    if (selectedId.current) loadDetail(selectedId.current, { force: true });
    fetchAll();
    if (invLoaded.current) fetchInventory();
  }), [clearDetail, loadDetail, patchStore, fetchAll, fetchInventory]);

  useEffect(() => {
    if (!flash) return undefined;
    const t = setTimeout(() => setFlash(""), 6000);
    return () => clearTimeout(t);
  }, [flash]);

  const onStoreSaved = (store, edited) => {
    setForm(null);
    setFlash(edited ? `Saved ${store.name}. Its new details now show across the CRM.` : `Added ${store.name}.`);
    announceStoreChanged(store);
  };

  // after the backend confirms: counts, lists, the drawer and other screens refresh
  const onStatusChanged = (store) => {
    setStatusFor(null);
    setFlash(store.is_active
      ? `${store.name} is active again — new operations can be recorded there.`
      : `${store.name} is now inactive — new operations there are blocked. Its history is unchanged.`);
    announceStoreChanged(store);
  };

  // the Active / Inactive cards open the channel list filtered to that status
  const filterByStatus = (status) => {
    setStatusFilter(status);
    setView("channels");
  };

  const selectView = (id) => {
    if (id === "channels") setStatusFilter("all");
    setView(id);
    if (id === "inventory" && !inv.data && !inv.loading) fetchInventory();
  };

  const openStore = (sp, el) => {
    opener.current = el || null;
    setSelected(sp);
    detail.load(sp.id);
  };
  const { cancel } = detail;
  const closeStore = useCallback(() => {
    cancel();
    setSelected(null);
    opener.current?.focus?.();
  }, [cancel]);

  // P&L opens in place of the list, which stays mounted (search, filters and
  // scroll are kept); it gets its own history entry so browser Back returns here.
  const openProfitLoss = (sp) => {
    if (!canViewPL) return;
    cancel();
    setSelected(null);
    const state = { ...(window.history.state || {}), view: "storeLocator", pl: sp.id };
    if (plStoreId === null) {
      savedScroll.current = scrollRef.current?.scrollTop || 0;
      window.history.pushState(state, "", window.location.href);
    } else {
      window.history.replaceState(state, "", window.location.href);
    }
    setPlStoreId(sp.id);
    scrollRef.current?.scrollTo({ top: 0 });
  };
  const closeProfitLoss = () => {
    if (window.history.state?.pl) window.history.back();
    else setPlStoreId(null);
  };
  useEffect(() => {
    const onPop = () => setPlStoreId(window.history.state?.pl ?? null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    if (plStoreId === null && scrollRef.current) scrollRef.current.scrollTop = savedScroll.current;
  }, [plStoreId]);

  const openInventory = (storeId, level = "all") => {
    cancel();
    setSelected(null);
    setFocus({ mode: "store", storeId, level });
    selectView("inventory");
  };

  const { points, counts, users, roles } = data;
  const loading = refreshing && !points;
  const shops = points?.filter(isShop).length ?? 0;
  const unassigned = users?.filter((u) => !u.stock_point && !u.sees_all_stores && (u.staff_kind || "store") === "store").length ?? 0;
  const myStore = !ownerView && points?.[0];
  const inactive = canManageStatus ? (points?.filter((p) => p.is_active === false).length ?? 0) : 0;
  // the open drawer always shows the latest copy of its store
  const shownStore = (selected && points?.find((p) => p.id === selected.id)) || selected;

  let body;
  if (errors.points && !points) {
    body = errors.points.status === 403 ? (
      <StateBox icon={Lock} title="You don't have access to stock points" text="Your account isn't allowed to view stores and channels." />
    ) : (
      <StateBox tone="error" icon={AlertTriangle} title="Couldn't load stores and channels"
        text={errors.points.message || "The server didn't respond. Check your connection and try again."}
        action={<PillButton icon={RefreshCw} onClick={refresh} className="mt-2">Try again</PillButton>} />
    );
  } else if (loading) {
    body = <div className="sl-stack">{[0, 1, 2, 3].map((i) => <Skel key={i} h={62} r={13} className="block" />)}</div>;
  } else if (view === "channels") {
    body = points.length ? (
      <ChannelsView points={points} counts={counts} countsFailed={errors.counts} selectedId={selected?.id}
        onOpen={openStore} onOpenInventory={openInventory} onEdit={canManageStores ? (sp) => setForm({ store: sp }) : undefined}
        onProfitLoss={canViewPL ? openProfitLoss : undefined} ownerView={ownerView}
        showStatus={canManageStatus} statusFilter={statusFilter} onStatusFilter={setStatusFilter} />
    ) : (
      <StateBox icon={Store} title="No stock points configured yet"
        text={canManageStores ? "Add your first shop or online channel to start tracking its stock and staff." : "Once the Owner adds a shop or channel it appears here."}
        action={canManageStores && <PillButton icon={Plus} primary onClick={() => setForm({ store: null })} className="mt-2">Add store</PillButton>} />
    );
  } else if (view === "staff") {
    body = users ? (
      <StaffView users={users} points={points} counts={counts} ownerView={ownerView} onOpenStore={openStore} onOpenInventory={openInventory}
        onOpenLogs={canViewOwnLogs ? setLogsFor : undefined} />
    ) : <StateBox tone="error" icon={AlertTriangle} title="Staff couldn't be loaded" text={errors.users?.message} />;
  } else if (view === "roles") {
    body = roles ? <RolesView roles={roles} users={users || []} ownerView={ownerView} /> : (
      <StateBox tone="error" icon={AlertTriangle} title="Roles couldn't be loaded" text={errors.roles?.message} />
    );
  } else {
    body = (
      <InventoryView inv={inv.data} error={inv.error} loading={inv.loading && !inv.data} onRetry={fetchInventory}
        focus={focus} onFocus={setFocus} ownerView={ownerView} onOpenStore={openStore} />
    );
  }

  const unavailable = "Unavailable";
  const plStore = canViewPL && plStoreId !== null ? points?.find((p) => p.id === plStoreId) : null;
  return (
    <PageFrame
      scrollRef={scrollRef}
      scope={ownerView
        ? <Badge tone="violet" icon={Building2}>Owner view · all stores &amp; channels</Badge>
        : <Badge icon={Store}>Your store · {me.stock_point_name}</Badge>}
      actions={<>
        <PillButton icon={RefreshCw} onClick={refresh} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</PillButton>
        {canViewOwnLogs && <PillButton icon={History} onClick={() => setLogsFor(me)}>My activity</PillButton>}
        {canManageStores && <PillButton icon={Plus} primary onClick={() => setForm({ store: null })} disabled={!points}>Register Store</PillButton>}
      </>}
    >
      {plStore && (
        <ProfitLoss store={plStore} stores={points} ownerView={ownerView} onBack={closeProfitLoss}
          onSwitchStore={(id) => { const sp = points.find((p) => p.id === id); if (sp) openProfitLoss(sp); }} />
      )}
      <div hidden={!!plStore}>
      {flash && <div className="sl-flash"><Alert tone="ok">{flash}</Alert></div>}
      <div className="sl-sums" style={{ "--sl-sum-cols": canManageStatus ? 5 : 3 }}>
        <SummaryCard id="channels" icon={Building2} tone="blue" label="Total Channels" view={view} onSelect={selectView} loading={loading}
          pressed={view === "channels" && statusFilter === "all"}
          value={points ? points.length : unavailable}
          sub={points ? (ownerView ? `${plural(shops, "shop")} · ${plural(points.length - shops, "online channel")}` : myStore?.name) : undefined} />
        {canManageStatus && (
          <>
            <SummaryCard id="active" icon={CircleCheck} tone="green" label="Active Channels" onSelect={filterByStatus} loading={loading}
              pressed={view === "channels" && statusFilter === "active"}
              value={points ? points.length - inactive : unavailable} sub={points ? "Open for new operations" : undefined} />
            <SummaryCard id="inactive" icon={CircleOff} tone="grey" label="Inactive Channels" onSelect={filterByStatus} loading={loading}
              pressed={view === "channels" && statusFilter === "inactive"}
              value={points ? inactive : unavailable} sub={points ? "New operations blocked" : undefined} />
          </>
        )}
        <SummaryCard id="staff" icon={Users} tone="amber" label="Total Staffs" view={view} onSelect={selectView} loading={loading}
          value={users ? users.length : unavailable}
          sub={users ? (ownerView ? `${num(unassigned)} without a Store Location` : "At your store") : undefined} />
        <SummaryCard id="roles" icon={KeyRound} tone="violet" label="Total Roles" view={view} onSelect={selectView} loading={loading}
          value={roles ? roles.length : unavailable} sub={roles ? "Role records" : undefined} />
      </div>

      <div className="sl-viewbar" role="tablist" aria-label="Dashboard sections">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} onClick={(e) => {
            selectView(v.id);
            e.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
          }}>
            <v.icon size={14} aria-hidden="true" />{v.label}
          </button>
        ))}
      </div>

      <div className="sl-view" role="tabpanel" aria-label={VIEWS.find((v) => v.id === view)?.label}>{body}</div>
      </div>

      {selected && (
        <StoreDrawer sp={shownStore} state={detail.state} onClose={closeStore} ownerView={ownerView} paused={!!form || !!statusFor}
          onReload={() => detail.load(selected.id, { force: true })} onOpenInventory={openInventory}
          onEdit={canManageStores ? (sp) => setForm({ store: sp }) : undefined}
          onSetStatus={canManageStatus ? setStatusFor : undefined}
          onProfitLoss={canViewPL ? openProfitLoss : undefined} />
      )}
      {form && <StoreForm store={form.store} points={points || []} onClose={() => setForm(null)} onSaved={onStoreSaved} />}
      {statusFor && <StoreStatusDialog store={statusFor} onClose={() => setStatusFor(null)} onDone={onStatusChanged} />}
      {logsFor && (
        <StaffLogsDialog user={logsFor} onClose={() => setLogsFor(null)}
          candidates={canViewOthersLogs ? (users || []).filter((u) => u.can_view_activity) : []} />
      )}
    </PageFrame>
  );
}

function PendingAssignment() {
  return (
    <PageFrame scope={<Badge tone="amber" icon={Lock}>Store assignment pending</Badge>}>
      <div className="sl-pending" role="status">
        <span className="sl-pending-icon" aria-hidden="true"><MapPin size={26} /></span>
        <h2 className="sl-pending-title">Store assignment pending</h2>
        <p className="sl-pending-text">{PENDING_MESSAGE}</p>
        <p className="sl-note">Store, inventory and staff data stay hidden until the Owner assigns you to a shop in Settings → Roles &amp; access.</p>
      </div>
    </PageFrame>
  );
}

function PageFrame({ scope, actions, children, scrollRef }) {
  return (
    <div className="sl-page">
      <div className="sl-head">
        <PageHeader title="Store & Channel Management" subtitle="Monitor locations, inventory availability and team assignments." actions={actions} />
        {scope && <div className="sl-scope">{scope}</div>}
      </div>
      <div className="sl-scroll" ref={scrollRef}>{children}</div>
    </div>
  );
}

export default function StoreLocator() {
  const { me } = useSession();
  if (!me?.sees_all_stores && !me?.stock_point) return <PendingAssignment />;
  return <Management me={me} />;
}
