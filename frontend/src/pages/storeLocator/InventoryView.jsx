import { useMemo, useState } from "react";
import { AlertTriangle, Boxes, Cpu, Layers, PackageSearch, RefreshCw, Warehouse } from "lucide-react";
import { PillButton, SearchInput } from "../../components/Atoms";
import { StockRows } from "./StoreDetail";
import { Badge, Panel, SelectPill, Segmented, Skel, StateBox, StoreMark } from "./shared";
import { LOW_STOCK_AT, STATE_LABEL, STATE_TONE, kindLabel, num, plural, stockState } from "./format";

/*
 * Inventory across the stock points this account may see, from
 * GET /stock-points/inventory/ (store-scoped by the backend).
 *
 *   By channel -- one row per shop / online channel, its own units only
 *   By product -- each variant's quantity at every visible stock point
 *   By store   -- one stock point's stock records
 *
 * A stock record at 0 is "Out of stock". A variant with no record at a
 * stock point is "No stock record" -- never counted as a zero.
 */

const MODES = [
  { id: "channel", label: "By channel" },
  { id: "product", label: "By product" },
  { id: "store", label: "By store" },
];
const LEVELS = (counts) => [
  { id: "all", label: "All inventory", count: counts?.all },
  { id: "in", label: "In stock", count: counts?.in },
  { id: "low", label: "Low stock", count: counts?.low },
  { id: "out", label: "Out of stock", count: counts?.out },
];

function tally(records, threshold) {
  const c = { all: records.length, in: 0, low: 0, out: 0, units: 0 };
  records.forEach((r) => {
    c[stockState(r.quantity, threshold)] += 1;
    c.units += r.quantity;
  });
  return c;
}

export default function InventoryView({ inv, error, loading, onRetry, focus, onFocus, ownerView, onOpenStore }) {
  const [q, setQ] = useState("");
  const threshold = inv?.low_stock_threshold ?? LOW_STOCK_AT;
  const points = useMemo(() => inv?.stock_points ?? [], [inv]);
  const pointById = useMemo(() => Object.fromEntries(points.map((p) => [p.id, p])), [points]);
  const { mode, storeId, level } = focus;
  const store = pointById[storeId] || points[0] || null;
  const set = (patch) => onFocus({ ...focus, ...patch });

  // Flatten once: every stock record with its variant's details.
  const records = useMemo(() => {
    if (!inv) return [];
    return inv.variants.flatMap((v) => v.stock.map((s) => ({
      ...v, ...s, key: s.id, store_name: pointById[s.stock_point_id]?.name || "—",
    })));
  }, [inv, pointById]);

  const byChannel = useMemo(() => points.map((p) => {
    const mine = records.filter((r) => r.stock_point_id === p.id);
    const parts = (inv?.parts ?? []).flatMap((pt) => pt.stock.filter((s) => s.stock_point_id === p.id));
    const recorded = new Set(mine.map((r) => r.variant_id));
    return {
      point: p,
      ...tally(mine, threshold),
      noRecord: (inv?.variants.length ?? 0) - recorded.size,
      partUnits: parts.reduce((a, s) => a + s.quantity, 0),
      partRecords: parts.length,
    };
  }), [points, records, inv, threshold]);

  if (error) {
    return (
      <StateBox tone="error" icon={AlertTriangle} title="Inventory couldn't be loaded"
        text={`${error.message || "The server didn't respond."} No quantities are shown rather than guessing them.`}
        action={<PillButton icon={RefreshCw} onClick={onRetry} className="mt-2">Try again</PillButton>} />
    );
  }
  if (!inv || loading) {
    return (
      <div className="sl-stack" aria-label="Loading inventory">
        <Skel h={44} r={999} className="block" />
        {[0, 1, 2, 3].map((i) => <Skel key={i} h={64} r={13} className="block" />)}
      </div>
    );
  }
  if (!points.length) {
    return <StateBox icon={Warehouse} title="No stock points to show" text="There are no shops or channels in your scope." />;
  }

  const needle = q.trim().toLowerCase();
  const matches = (v) => !needle || [v.product_name, v.brand, v.model_name, v.product_code, v.variant_code, v.spec, v.location]
    .some((x) => (x || "").toLowerCase().includes(needle));

  return (
    <div className="sl-stack">
      <div className="sl-tools">
        <Segmented label="Inventory view" options={MODES} value={mode} onChange={(m) => set({ mode: m })} />
        {mode !== "channel" && (
          <SearchInput value={q} onChange={(e) => setQ(e.target.value)} onClear={() => setQ("")} placeholder="Search product, brand, code or spec" />
        )}
        {mode !== "channel" && ownerView && points.length > 1 && (
          <SelectPill label="Store" value={mode === "store" ? store?.id ?? "" : storeId ?? "all"}
            onChange={(v) => set({ storeId: v === "all" ? null : Number(v) })}>
            {mode === "product" && <option value="all">All stores & channels</option>}
            {points.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </SelectPill>
        )}
      </div>

      {mode === "channel" && <ChannelTable rows={byChannel} threshold={threshold} onPick={(id, lvl) => set({ mode: "store", storeId: id, level: lvl })} onOpenStore={onOpenStore} />}
      {mode === "product" && (
        <ProductMatrix inv={inv} points={storeId && pointById[storeId] ? [pointById[storeId]] : points} threshold={threshold}
          level={level} onLevel={(l) => set({ level: l })} matches={matches} />
      )}
      {mode === "store" && store && (
        <StoreInventory inv={inv} store={store} records={records.filter((r) => r.stock_point_id === store.id && matches(r))}
          threshold={threshold} level={level} onLevel={(l) => set({ level: l })} matches={matches} />
      )}
    </div>
  );
}

function ChannelTable({ rows, threshold, onPick, onOpenStore }) {
  const count = (id, lvl, value, tone) => (
    value ? (
      <button type="button" className="sl-count-btn" data-tone={tone} onClick={() => onPick(id, lvl)}
        aria-label={`${num(value)} ${STATE_LABEL[lvl] || "records"} — open filtered inventory`}>
        {num(value)}
      </button>
    ) : <span className="sl-count-zero">0</span>
  );
  return (
    <>
      <div className="sl-table" role="table" aria-label="Inventory by channel">
        <div className="sl-tr sl-th sl-tr-inv" role="row">
          <span role="columnheader">Store / channel</span>
          <span role="columnheader" className="sl-num">Units</span>
          <span role="columnheader" className="sl-num">Records</span>
          <span role="columnheader" className="sl-num">In stock</span>
          <span role="columnheader" className="sl-num">Low</span>
          <span role="columnheader" className="sl-num">Out</span>
          <span role="columnheader" className="sl-num">Spare parts</span>
        </div>
        {rows.map((r) => (
          <div key={r.point.id} className="sl-tr sl-tr-inv" role="row">
            <span role="cell" className="sl-td-main">
              <StoreMark sp={r.point} size="sm" />
              <span className="min-w-0">
                <button type="button" className="sl-link-btn" onClick={() => onOpenStore?.(r.point)} title={r.point.name}>{r.point.name}</button>
                <span className="sl-row-sub">{kindLabel(r.point)}{r.noRecord > 0 ? ` · ${plural(r.noRecord, "variant")} with no record here` : ""}</span>
              </span>
            </span>
            <span role="cell" className="sl-num" data-label="Units"><b>{num(r.units)}</b></span>
            <span role="cell" className="sl-num" data-label="Records">{count(r.point.id, "all", r.all, "grey")}</span>
            <span role="cell" className="sl-num" data-label="In stock">{count(r.point.id, "in", r.in, "green")}</span>
            <span role="cell" className="sl-num" data-label="Low">{count(r.point.id, "low", r.low, "amber")}</span>
            <span role="cell" className="sl-num" data-label="Out">{count(r.point.id, "out", r.out, "red")}</span>
            <span role="cell" className="sl-num" data-label="Spare parts">{num(r.partUnits)} <small>({plural(r.partRecords, "record")})</small></span>
          </div>
        ))}
      </div>
      <p className="sl-note">
        Each row counts only that stock point's own records — nothing is added twice. Low stock = 1–{threshold} units, the CRM's existing rule.
        Product and spare-part units are kept separate.
      </p>
    </>
  );
}

function ProductMatrix({ inv, points, threshold, level, onLevel, matches }) {
  const ids = new Set(points.map((p) => p.id));
  const rows = inv.variants.filter(matches).map((v) => {
    const cells = points.map((p) => {
      const rec = v.stock.find((s) => s.stock_point_id === p.id);
      return { point: p, quantity: rec ? rec.quantity : null, location: rec?.location };
    });
    const states = cells.map((c) => stockState(c.quantity, threshold));
    const total = v.stock.filter((s) => ids.has(s.stock_point_id)).reduce((a, s) => a + s.quantity, 0);
    return { v, cells, states, total };
  });
  const counts = { all: rows.length };
  ["in", "low", "out"].forEach((k) => { counts[k] = rows.filter((r) => r.states.includes(k)).length; });
  const shown = level === "all" ? rows : rows.filter((r) => r.states.includes(level));

  return (
    <>
      <Segmented label="Stock level" options={LEVELS(counts)} value={level} onChange={onLevel} />
      <p className="sl-note">
        A product is listed under a level when at least one {points.length > 1 ? "of these stock points" : "record here"} is at that level.
        “No record” means the variant isn't stocked there at all — it is not a zero.
      </p>
      {shown.length ? (
        <ul className="sl-matrix">
          {shown.map(({ v, cells, total }) => (
            <li key={v.variant_id} className="sl-matrix-row">
              <div className="sl-matrix-head">
                <div className="min-w-0">
                  <p className="sl-row-name">{v.product_name}<span className="sl-bars-spec"> · {v.spec}</span></p>
                  <p className="sl-row-sub">{v.product_code} · {v.variant_code}</p>
                </div>
                <Badge tone="grey" title="Units across the stock points shown">{num(total)} units</Badge>
              </div>
              <div className="sl-cells">
                {cells.map((c) => {
                  const st = stockState(c.quantity, threshold);
                  return (
                    <span key={c.point.id} className="sl-cell" data-state={st} title={c.location ? `Bin: ${c.location}` : undefined}>
                      <span className="sl-cell-store">{c.point.name}</span>
                      <span className="sl-cell-qty">{st === "none" ? "No record" : st === "out" ? "Out · 0" : num(c.quantity)}</span>
                    </span>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <StateBox compact icon={PackageSearch} title="No products match" text="Change the search or the stock level." />
      )}
    </>
  );
}

function StoreInventory({ inv, store, records, threshold, level, onLevel, matches }) {
  const counts = tally(records, threshold);
  const shown = level === "all" ? records : records.filter((r) => stockState(r.quantity, threshold) === level);
  const unrecorded = inv.variants.filter((v) => matches(v) && !v.stock.some((s) => s.stock_point_id === store.id));
  const parts = inv.parts
    .map((p) => ({ ...p, rec: p.stock.find((s) => s.stock_point_id === store.id) }))
    .filter((p) => p.rec);
  const [showUnrecorded, setShowUnrecorded] = useState(false);

  return (
    <>
      <div className="sl-store-strip">
        <StoreMark sp={store} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="sl-row-name">{store.name}</p>
          <p className="sl-row-sub">{kindLabel(store)} · {num(counts.units)} product units in {plural(counts.all, "stock record")}</p>
        </div>
      </div>
      <Segmented label="Stock level" options={LEVELS(counts)} value={level} onChange={onLevel} />
      {shown.length ? <StockRows rows={shown} threshold={threshold} /> : (
        <StateBox compact icon={Boxes} title={records.length ? "Nothing at this stock level" : "No product stock recorded here"}
          text={records.length ? "Pick another level or clear the search." : "Stock added from Inventory → Add stock will appear here."} />
      )}

      <Panel icon={Layers} title={`${plural(unrecorded.length, "variant")} with no stock record here`}
        action={unrecorded.length > 0 && (
          <button type="button" className="sl-text-btn" aria-expanded={showUnrecorded} onClick={() => setShowUnrecorded((s) => !s)}>
            {showUnrecorded ? "Hide" : "Show"}
          </button>
        )}>
        <p className="sl-note">These catalogue variants have never been stocked at {store.name}. They're listed separately because a missing record isn't the same as a verified zero.</p>
        {showUnrecorded && (
          <ul className="sl-list mt-2">
            {unrecorded.map((v) => (
              <li key={v.variant_id}>
                <div className="min-w-0"><p className="sl-row-name">{v.product_name}</p><p className="sl-row-sub">{v.variant_code} · {v.spec}</p></div>
                <Badge tone={STATE_TONE.none}>No record</Badge>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel icon={Cpu} title={`Spare parts at ${store.name}`}>
        {parts.length ? (
          <ul className="sl-list">
            {parts.map((p) => (
              <li key={p.part_id}>
                <div className="min-w-0"><p className="sl-row-name">{p.name}</p><p className="sl-row-sub">{p.slug}{p.compatible_brands?.length ? ` · fits ${p.compatible_brands.join(", ")}` : ""}</p></div>
                <Badge tone={STATE_TONE[stockState(p.rec.quantity, threshold)]}>{p.rec.quantity === 0 ? "Out · 0" : `${num(p.rec.quantity)} in stock`}</Badge>
              </li>
            ))}
          </ul>
        ) : <StateBox compact icon={Cpu} title="No spare-part stock recorded here" />}
      </Panel>
    </>
  );
}
