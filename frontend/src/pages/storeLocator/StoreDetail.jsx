import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowRight, Boxes, Building2, Cpu, ExternalLink, Lock, MapPin, Navigation, Package, PackageX, Pencil,
  Phone, Power, PowerOff, Receipt, RefreshCw, Repeat2, ShieldCheck, TrendingDown, UserCheck, Users, Warehouse, Wrench, X, TrendingUp,
} from "lucide-react";
import { fmt, money } from "../../lib/theme";
import { PillButton, SearchInput } from "../../components/Atoms";
import { Badge, KindBadge, Kpi, Panel, Restricted, SelectPill, Segmented, Skel, StateBox, StatusBadge, StoreMark } from "./shared";
import { LOW_STOCK_AT, STATE_TONE, firstLine, initials, isShop, kindLabel, mapSearchUrl, num, plural, stockState } from "./format";

/*
 * One store / channel in detail -- the Owner opens it as a drawer from the
 * channel table. All data comes from GET /stock-points/<id>/locator/,
 * which the backend scopes to the requesting account's store.
 */

const REPAIR_TONE = { Received: "grey", Diagnosing: "amber", "In progress": "blue", "Ready for pickup": "violet", Delivered: "green" };
const INVOICE_TONE = { Paid: "green", Refunded: "grey", "Payment link sent": "amber", Overdue: "red", Cancelled: "grey" };
const ASSET_TONE = { available: "green", reserved: "amber", rented: "blue", maintenance: "violet", retired: "grey" };

const TABS = [
  { id: "overview", label: "Overview", icon: Building2 },
  { id: "products", label: "Products", icon: Package },
  { id: "parts", label: "Spare parts", icon: Cpu },
  { id: "staff", label: "Staff", icon: Users },
  { id: "activity", label: "Activity", icon: Receipt },
];

function inventoryFigures(data) {
  const units = data.stock.reduce((a, s) => a + s.quantity, 0);
  const out = data.stock.filter((s) => s.quantity === 0).length;
  const low = data.stock.filter((s) => s.quantity > 0 && s.quantity <= LOW_STOCK_AT).length;
  const partUnits = data.parts.reduce((a, p) => a + p.quantity, 0);
  return { units, out, low, partUnits, records: data.stock.length };
}

function DetailHero({ sp, data, loading, onReload, onClose, onEdit, onSetStatus, onOpenInventory, onProfitLoss, titleId, closeRef }) {
  const fig = data ? inventoryFigures(data) : null;
  // status controls only for administrators -- they're the only ones the API sends is_active to
  const canSetStatus = onSetStatus && typeof sp.is_active === "boolean";
  return (
    <div className="sl-hero">
      <div className="sl-hero-top">
        <StoreMark sp={sp} size="lg" />
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="sl-hero-title">{sp.name}</h2>
          <div className="sl-hero-meta">
            <KindBadge sp={sp} />
            <StatusBadge sp={sp} />
            {sp.gstin && <Badge tone="grey" icon={ShieldCheck}>Own GSTIN</Badge>}
            {sp.address ? (
              <span className="sl-hero-addr"><MapPin size={13} aria-hidden="true" />{firstLine(sp.address)}</span>
            ) : data ? (
              <span className="sl-hero-addr" data-empty="true"><MapPin size={13} aria-hidden="true" />{isShop(sp) ? "Address not configured" : "Online channel — no physical location"}</span>
            ) : null}
          </div>
        </div>
        <div className="sl-hero-actions">
          {onEdit && (
            <button type="button" className="sl-icon-btn" onClick={() => onEdit(sp)} aria-label={`Edit ${sp.name}`} title="Edit store">
              <Pencil size={16} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="sl-icon-btn" onClick={onReload} disabled={loading} aria-label="Reload store details" title="Reload">
            <RefreshCw size={16} aria-hidden="true" className={loading ? "animate-spin motion-reduce:animate-none" : undefined} />
          </button>
          {onClose && (
            <button ref={closeRef} type="button" className="sl-icon-btn" onClick={onClose} aria-label="Close store details">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      <div className="sl-kpis" aria-busy={!data}>
        {fig ? (
          <>
            <Kpi label="Product units" value={num(fig.units)} />
            <Kpi label="Stock records" value={num(fig.records)} />
            <Kpi label="Spare-part units" value={num(fig.partUnits)} />
            <Kpi label="Staff assigned" value={num(data.staff.filter((s) => s.is_active).length)} />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="sl-kpi"><Skel w="45%" h={20} className="block" /><Skel w="70%" h={9} className="mt-2 block" /></div>
          ))
        )}
      </div>
      {sp.is_active === false && (
        <p className="sl-inactive-note" role="status">
          Inactive — no new sales, repairs, rentals, stock or staff assignments can be recorded here. Existing records are unchanged.
        </p>
      )}
      {(onOpenInventory || canSetStatus || onProfitLoss) && (
        <div className="sl-hero-foot">
          {onOpenInventory && (
            <button type="button" className="sl-text-btn" onClick={() => onOpenInventory(sp.id, "all")}>
              <Warehouse size={14} aria-hidden="true" />Open full inventory view<ArrowRight size={13} aria-hidden="true" />
            </button>
          )}
          {onProfitLoss && (
            <button type="button" className="sl-text-btn" onClick={() => onProfitLoss(sp)}>
              <TrendingUp size={14} aria-hidden="true" />Profit &amp; Loss<ArrowRight size={13} aria-hidden="true" />
            </button>
          )}
          {canSetStatus && (
            <button type="button" className="sl-status-btn" data-action={sp.is_active ? "deactivate" : "activate"}
              onClick={() => onSetStatus(sp)} aria-haspopup="dialog">
              {sp.is_active ? <PowerOff size={14} aria-hidden="true" /> : <Power size={14} aria-hidden="true" />}
              {sp.is_active ? "Deactivate" : "Reactivate"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Signal({ icon: Icon, tone, label, value, note, onClick }) {
  const body = (
    <>
      <span className="sl-signal-icon"><Icon size={16} aria-hidden="true" /></span>
      <span className="min-w-0">
        <span className="sl-signal-value">{value}</span>
        <span className="sl-signal-label">{label}</span>
        {note && <span className="sl-signal-note">{note}</span>}
      </span>
    </>
  );
  return onClick ? (
    <button type="button" className="sl-signal" data-tone={tone} onClick={onClick}>{body}</button>
  ) : (
    <div className="sl-signal" data-tone={tone}>{body}</div>
  );
}

function OverviewTab({ sp, data, onTab, onOpenInventory }) {
  const fig = inventoryFigures(data);
  const top = [...data.stock].sort((a, b) => b.quantity - a.quantity).filter((s) => s.quantity > 0).slice(0, 5);
  const maxQty = Math.max(1, ...top.map((t) => t.quantity));
  const { repairs, invoices } = data;
  const tel = sp.phone ? `tel:${sp.phone.replace(/[^\d+]/g, "")}` : null;
  const open = (filter) => (onOpenInventory ? () => onOpenInventory(sp.id, filter) : () => onTab("products"));
  return (
    <div className="sl-overview">
      <Panel icon={TrendingDown} title="At a glance" className="sl-span-2">
        <div className="sl-signals">
          <Signal icon={PackageX} tone={fig.out ? "red" : "green"} label="Out of stock (0 units)" value={num(fig.out)} onClick={open("out")} />
          <Signal icon={TrendingDown} tone={fig.low ? "amber" : "green"} label={`Low stock (1–${LOW_STOCK_AT} units)`} value={num(fig.low)} onClick={open("low")} />
          {repairs.restricted ? (
            <Signal icon={Lock} tone="grey" label="Open repair tickets" value="—" note="Not in your role" />
          ) : (
            <Signal icon={Wrench} tone={repairs.open ? "blue" : "green"} label="Open repair tickets" value={num(repairs.open)} onClick={() => onTab("activity")} />
          )}
          {invoices.restricted ? (
            <Signal icon={Lock} tone="grey" label="Outstanding to collect" value="—" note="Not in your role" />
          ) : (
            <Signal icon={Receipt} tone={invoices.outstanding ? "amber" : "green"} label="Outstanding to collect" value={money(invoices.outstanding)}
              note={invoices.outstanding_count ? plural(invoices.outstanding_count, "unpaid invoice") : undefined} onClick={() => onTab("activity")} />
          )}
        </div>
      </Panel>

      <Panel
        icon={Boxes}
        title="Most stocked here"
        action={data.stock.length > 0 && (
          <button type="button" className="sl-text-btn" onClick={() => onTab("products")}>All products <ArrowRight size={13} aria-hidden="true" /></button>
        )}
      >
        {top.length ? (
          <ul className="sl-bars">
            {top.map((s) => (
              <li key={s.id}>
                <div className="sl-bars-row">
                  <span className="sl-bars-name">{s.product_name}<span className="sl-bars-spec"> · {s.spec}</span></span>
                  <span className="sl-bars-qty">{num(s.quantity)}</span>
                </div>
                <span className="sl-bar" aria-hidden="true"><span style={{ width: `${(s.quantity / maxQty) * 100}%` }} /></span>
              </li>
            ))}
          </ul>
        ) : (
          <StateBox compact icon={Package} title="No units in stock here" text={data.stock.length ? "Every stock record here is at zero." : "No product stock is recorded at this stock point yet."} />
        )}
      </Panel>

      <Panel icon={MapPin} title="Location & contact">
        <dl className="sl-kv">
          <div><dt>Type</dt><dd>{kindLabel(sp)}</dd></div>
          <div>
            <dt>Phone</dt>
            {tel ? <dd><a className="sl-inline-link" href={tel}>{sp.phone}</a></dd> : <dd data-empty="true">Not configured</dd>}
          </div>
          <div className="sl-kv-wide">
            <dt>{isShop(sp) ? "Address" : "Location"}</dt>
            {sp.address ? <dd style={{ whiteSpace: "pre-line" }}>{sp.address}</dd> : (
              <dd data-empty="true">{isShop(sp) ? "Address not configured" : "Online sales channel — no physical address"}</dd>
            )}
          </div>
          <div>
            <dt>GSTIN</dt>
            {sp.gstin ? <dd className="sl-mono">{sp.gstin}</dd> : <dd data-empty="true">Not set — invoices use the business-wide GSTIN</dd>}
          </div>
          <div><dt>Code</dt><dd className="sl-mono">{sp.slug}</dd></div>
        </dl>
        {(sp.address || tel) && (
          <div className="sl-contact-actions">
            {sp.address && (
              <a className="sl-link" href={mapSearchUrl(sp.address)} target="_blank" rel="noopener noreferrer">
                <Navigation size={13} aria-hidden="true" />Search address on map<ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
            {tel && <a className="sl-link" href={tel}><Phone size={13} aria-hidden="true" />Call store</a>}
          </div>
        )}
        <p className="sl-note mt-2">
          {sp.address
            ? "No GPS coordinates are stored — the map link searches the saved address text."
            : isShop(sp) ? "Add an address to this shop to enable a map search link." : "Online channels have no map location."}
        </p>
      </Panel>
    </div>
  );
}

function ProductsTab({ rows, onOpenInventory, spId }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("name");

  const counts = useMemo(() => {
    const c = { all: rows.length, in: 0, low: 0, out: 0 };
    rows.forEach((r) => { c[stockState(r.quantity)] += 1; });
    return c;
  }, [rows]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = rows.filter((r) => {
      if (filter !== "all" && stockState(r.quantity) !== filter) return false;
      if (!needle) return true;
      return [r.product_name, r.brand, r.model_name, r.product_code, r.variant_code, r.spec, r.processor, r.location]
        .some((v) => (v || "").toLowerCase().includes(needle));
    });
    const by = {
      name: (a, b) => a.product_name.localeCompare(b.product_name) || a.variant_code.localeCompare(b.variant_code),
      qtyDesc: (a, b) => b.quantity - a.quantity,
      qtyAsc: (a, b) => a.quantity - b.quantity,
    }[sort];
    return [...list].sort(by);
  }, [rows, q, filter, sort]);

  if (!rows.length) {
    return <StateBox icon={Package} title="No product stock recorded here" text="This stock point has no product or variant stock records yet. Stock added from Inventory → Add stock will appear here." />;
  }

  return (
    <>
      <div className="sl-tools">
        <SearchInput value={q} onChange={(e) => setQ(e.target.value)} onClear={() => setQ("")} placeholder="Search product, code, spec or bin" />
        <Segmented
          label="Stock level"
          value={filter}
          onChange={setFilter}
          options={[
            { id: "all", label: "All", count: counts.all },
            { id: "in", label: "In stock", count: counts.in },
            { id: "low", label: `Low (1–${LOW_STOCK_AT})`, count: counts.low },
            { id: "out", label: "Out", count: counts.out },
          ]}
        />
        <SelectPill label="Sort" value={sort} onChange={setSort}>
          <option value="name">Name A–Z</option>
          <option value="qtyDesc">Most units</option>
          <option value="qtyAsc">Fewest units</option>
        </SelectPill>
      </div>
      <p className="sl-note mb-2" aria-live="polite">
        {plural(shown.length, "stock record")} shown · low stock means {LOW_STOCK_AT} or fewer units at this stock point
        {onOpenInventory && (
          <> · <button type="button" className="sl-inline-btn" onClick={() => onOpenInventory(spId, filter)}>open in inventory view</button></>
        )}
      </p>
      {shown.length ? <StockRows rows={shown} /> : (
        <StateBox compact title="No stock matches these filters" text="Clear the search or pick another stock level." />
      )}
    </>
  );
}

export function StockRows({ rows, threshold = LOW_STOCK_AT, showStore }) {
  return (
    <div className="sl-rows" role="table" aria-label="Product stock">
      <div className="sl-row-head" role="row">
        <span role="columnheader">Product / variant</span>
        <span role="columnheader">{showStore ? "Store / channel" : "Spec · condition"}</span>
        <span role="columnheader">Price · bin</span>
        <span role="columnheader" className="sl-head-qty">Qty here</span>
      </div>
      {rows.map((r) => {
        const state = stockState(r.quantity, threshold);
        return (
          <div key={r.key ?? r.id} className="sl-row" role="row">
            <div className="sl-row-main" role="cell">
              <p className="sl-row-name">{r.product_name}</p>
              <p className="sl-row-sub">{r.product_code} · {r.variant_code}</p>
            </div>
            <span className="sl-row-qty" role="cell">
              <Badge tone={STATE_TONE[state]}>
                {state === "out" ? "Out · 0" : `${num(r.quantity)} unit${r.quantity === 1 ? "" : "s"}`}
              </Badge>
            </span>
            <div className="sl-row-meta">
              <span role="cell">
                {showStore ? (
                  <><span className="sl-cell-label">Store</span><b>{r.store_name}</b><span className="sl-row-extra">{r.spec}</span></>
                ) : (
                  <>
                    <span className="sl-cell-label">Spec</span>
                    <b>{r.spec}</b>
                    {(r.processor || r.condition) && (
                      <span className="sl-row-extra">{[r.processor, r.condition].filter(Boolean).join(" · ")}</span>
                    )}
                  </>
                )}
              </span>
              <span role="cell">
                <span className="sl-cell-label">Price</span>
                <span className="sl-price">{money(r.sell_price)}{r.mrp > r.sell_price && <s>{money(r.mrp)}</s>}</span>
                <span className="sl-row-extra" data-empty={!r.location}>
                  <span className="sl-cell-label">Bin</span>{r.location || "No bin set"}
                </span>
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PartsTab({ parts }) {
  if (!parts.length) {
    return <StateBox icon={Cpu} title="No spare-part stock recorded here" text="No repair parts have a stock record at this stock point." />;
  }
  return (
    <Panel icon={Cpu} title={`${plural(parts.length, "part")} with a stock record here`}>
      <ul className="sl-list">
        {parts.map((p) => (
          <li key={p.id}>
            <div className="min-w-0">
              <p className="sl-row-name">{p.name}</p>
              <p className="sl-row-sub">{p.slug}{p.compatible_brands?.length ? ` · fits ${p.compatible_brands.join(", ")}` : ""}</p>
            </div>
            <Badge tone={STATE_TONE[stockState(p.quantity)]}>{p.quantity === 0 ? "Out · 0" : `${num(p.quantity)} in stock`}</Badge>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ActivityTab({ data }) {
  const { repairs, invoices, rentals } = data;
  const maxStatus = repairs.restricted ? 0 : Math.max(1, ...repairs.by_status.map((s) => s.count));
  return (
    <div className="sl-overview">
      <Panel icon={Wrench} title="Repair tickets">
        {repairs.restricted ? <Restricted what="Repair tickets" /> : repairs.total === 0 ? (
          <StateBox compact icon={Wrench} title="No repair tickets at this stock point" />
        ) : (
          <>
            <div className="sl-minis">
              <Kpi label="All tickets" value={num(repairs.total)} />
              <Kpi label="Not delivered" value={num(repairs.open)} />
            </div>
            <div className="sl-status-grid">
              {repairs.by_status.map((s) => (
                <div key={s.status}>
                  <span>{s.status}</span>
                  <span className="sl-bar" aria-hidden="true"><span style={{ width: `${(s.count / maxStatus) * 100}%` }} /></span>
                  <span>{num(s.count)}</span>
                </div>
              ))}
            </div>
            <p className="sl-subhead">Most recent</p>
            <ul className="sl-list">
              {repairs.recent.map((t) => (
                <li key={t.id}>
                  <div className="min-w-0">
                    <p className="sl-row-name">{t.device}</p>
                    <p className="sl-row-sub">{t.code} · received {fmt(t.received)}</p>
                  </div>
                  <Badge tone={REPAIR_TONE[t.status] || "grey"}>{t.status}</Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>

      <Panel icon={Receipt} title="Sales & invoices">
        {invoices.restricted ? <Restricted what="Invoices" /> : invoices.count === 0 ? (
          <StateBox compact icon={Receipt} title="No invoices raised from this stock point"
            text={invoices.cancelled ? `${plural(invoices.cancelled, "cancelled invoice")} not counted.` : undefined} />
        ) : (
          <>
            <div className="sl-minis" data-cols="4">
              <Kpi label="Invoices" value={num(invoices.count)} />
              <Kpi label="Collected (net)" value={money(invoices.collected)} />
              <Kpi label="Outstanding" value={money(invoices.outstanding)} />
              <Kpi label="Unpaid invoices" value={num(invoices.outstanding_count)} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {invoices.by_source.map((s) => <Badge key={s.source} tone="grey">{s.label}: {num(s.count)}</Badge>)}
            </div>
            <p className="sl-note mt-2">
              All-time, cancelled invoices excluded{invoices.cancelled ? ` (${num(invoices.cancelled)} cancelled)` : ""}. Collected is net of refunds.
            </p>
            <p className="sl-subhead">Most recent</p>
            <ul className="sl-list">
              {invoices.recent.map((i) => (
                <li key={i.id}>
                  <div className="min-w-0">
                    <p className="sl-row-name sl-mono">{i.code}</p>
                    <p className="sl-row-sub">{fmt(i.date)} · {i.source} · {money(i.total)}</p>
                  </div>
                  <Badge tone={INVOICE_TONE[i.status] || "grey"}>{i.status}</Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>

      <Panel icon={Repeat2} title="Rental devices" className="sl-span-2">
        {rentals.restricted ? <Restricted what="Rental devices" /> : !rentals.assets.length ? (
          <StateBox compact icon={Repeat2} title="No rental devices linked to this stock point"
            text="Shows devices taken from, or returned to, this stock point's inventory." />
        ) : (
          <>
            <p className="sl-note mb-2">Devices taken from, or returned to, this stock point's sale stock.</p>
            <ul className="sl-list sl-list-cols">
              {rentals.assets.map((a) => (
                <li key={a.id}>
                  <div className="min-w-0">
                    <p className="sl-row-name">{`${a.brand} ${a.model_name}`.trim()}</p>
                    <p className="sl-row-sub">{a.asset_tag}{a.from_here && " · taken from here"}{a.returned_here && " · returned here"}</p>
                  </div>
                  <Badge tone={ASSET_TONE[a.status] || "grey"}>{a.status_label}</Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>
    </div>
  );
}

function StaffTab({ sp, staff, ownerView }) {
  if (!staff.length) {
    return (
      <StateBox
        icon={Users}
        title="No staff are assigned to this store yet"
        text={
          !isShop(sp)
            ? "Online channels aren't staff locations — staff are assigned to physical shops only."
            : ownerView
              ? "Assign a Store Location to team members in Settings → Roles & access. Roles and past activity are never treated as an assignment."
              : "Only the Owner can assign staff to a store."
        }
      />
    );
  }
  return (
    <Panel icon={UserCheck} title={`${plural(staff.length, "team member")} assigned`}>
      <ul className="sl-staff">
        {staff.map((u) => (
          <li key={u.id} data-inactive={!u.is_active}>
            <span className="sl-avatar" aria-hidden="true">{initials(u.name)}</span>
            <div className="min-w-0 flex-1">
              <p className="sl-row-name">{u.name}</p>
              <p className="sl-row-sub">{u.role || "No role"}</p>
            </div>
            <Badge tone={u.is_active ? "green" : "grey"}>{u.is_active ? "Active" : "Inactive"}</Badge>
          </li>
        ))}
      </ul>
      <p className="sl-note mt-3">Store Location is set by the Owner in Settings → Roles &amp; access.</p>
    </Panel>
  );
}

export function StoreDetail({ sp, state, onReload, onClose, onOpenInventory, onEdit, onSetStatus, onProfitLoss, ownerView, closeRef, titleId = "sl-detail-title" }) {
  const [tab, setTab] = useState("overview");
  const { data, error, loading } = state;
  const shown = data?.stock_point || sp;

  let body;
  if (error) {
    body = error.status === 404 || error.status === 403 ? (
      <StateBox icon={Lock} title="This store isn't available to your account" text="You can only open the store you're assigned to." />
    ) : (
      <StateBox
        tone="error"
        icon={AlertTriangle}
        title="Couldn't load this store's details"
        text={error.message || "The server didn't respond. Check your connection and try again."}
        action={<PillButton icon={RefreshCw} onClick={onReload} className="mt-2">Try again</PillButton>}
      />
    );
  } else if (!data) {
    body = (
      <div className="sl-overview" aria-label="Loading store details">
        <Skel h={118} r={13} className="sl-span-2 block" />
        <Skel h={180} r={13} className="block" />
        <Skel h={180} r={13} className="block" />
      </div>
    );
  } else if (tab === "overview") {
    body = <OverviewTab sp={shown} data={data} onTab={setTab} onOpenInventory={onOpenInventory} />;
  } else if (tab === "products") {
    body = <ProductsTab rows={data.stock} onOpenInventory={onOpenInventory} spId={shown.id} />;
  } else if (tab === "parts") {
    body = <PartsTab parts={data.parts} />;
  } else if (tab === "activity") {
    body = <ActivityTab data={data} />;
  } else {
    body = <StaffTab sp={shown} staff={data.staff} ownerView={ownerView} />;
  }

  return (
    <>
      <DetailHero sp={shown} data={data} loading={loading} onReload={onReload} onClose={onClose} onEdit={onEdit} onSetStatus={onSetStatus}
        onOpenInventory={onOpenInventory} onProfitLoss={onProfitLoss} titleId={titleId} closeRef={closeRef} />
      <div className="sl-tabs" role="tablist" aria-label="Store sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`sl-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="sl-tabpanel"
            onClick={(e) => {
              setTab(t.id);
              e.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
            }}
          >
            <t.icon size={14} aria-hidden="true" />
            {t.label}
          </button>
        ))}
      </div>
      <div className="sl-tabpanel" id="sl-tabpanel" role="tabpanel" aria-labelledby={`sl-tab-${tab}`} aria-busy={loading}>
        {body}
      </div>
    </>
  );
}

export function StoreDrawer({ sp, state, onClose, onReload, onOpenInventory, onEdit, onSetStatus, onProfitLoss, paused = false, ownerView = false }) {
  const panelRef = useRef(null);
  const closeRef = useRef(null);

  // Focus the close button on open; Escape closes; Tab stays inside.
  // `paused` while a dialog (the edit form) is open on top of the drawer.
  useEffect(() => { closeRef.current?.focus(); }, []);
  useEffect(() => {
    if (paused) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const items = [...panelRef.current.querySelectorAll('button:not(:disabled), a[href], input, select, [tabindex]:not([tabindex="-1"])')];
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, paused]);

  return (
    <>
      <div className="sl-overlay" aria-hidden="true" onClick={onClose} />
      <div ref={panelRef} className="sl-drawer" role="dialog" aria-modal="true" aria-labelledby="sl-drawer-title">
        <div className="sl-drawer-scroll">
          <StoreDetail sp={sp} state={state} onReload={onReload} onClose={onClose} onOpenInventory={onOpenInventory}
            onEdit={onEdit} onSetStatus={onSetStatus} onProfitLoss={onProfitLoss} ownerView={ownerView} closeRef={closeRef} titleId="sl-drawer-title" />
        </div>
      </div>
    </>
  );
}
