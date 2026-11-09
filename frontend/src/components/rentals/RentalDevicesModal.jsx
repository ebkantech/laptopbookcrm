import { useEffect, useMemo, useState } from "react";
import { History, PackageOpen, PencilLine, Plus, Undo2, X } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import DeviceHistoryModal from "./DeviceHistoryModal";

const STATUS_COLOR = { available: C.green, reserved: C.amber, rented: C.blue, maintenance: C.amber, retired: C.inkSoft };
const STATUS_LABEL = { available: "Free to rent", reserved: "Reserved", rented: "On rent", maintenance: "Maintenance", retired: "Retired" };
const digits = (v) => String(v ?? "").replace(/\D/g, "");

/*
 * The rental fleet: every laptop, what it cost, its rent per month and
 * where it is. A laptop is added here straight from Inventory (it leaves
 * that shop's sale stock), and a free one goes back on sale the same way:
 * +1 in a shop's stock, out of the fleet (its rental history is kept).
 */
export default function RentalDevicesModal({ assets, canManage, onClose, onChanged }) {
  const [shops, setShops] = useState([]);
  const [products, setProducts] = useState(null);
  const [returning, setReturning] = useState(null); // asset id
  const [shopId, setShopId] = useState("");
  const [editing, setEditing] = useState(null); // { id, purchase_price, monthly_rent }
  const [adding, setAdding] = useState(null); // { stock, serial, tag, purchase_price, monthly_rent }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [showRetired, setShowRetired] = useState(false);
  const [historyOf, setHistoryOf] = useState(null); // asset id

  // only active shops can take stock back (?active=1)
  useEffect(() => { if (canManage) api.getAll("/stock-points/?active=1").then(setShops); }, [canManage]);

  // laptops for sale in Inventory, one option per product x shop with stock
  const shelves = useMemo(() => (products || []).flatMap((p) => p.variants.flatMap((v) => v.stock
    .filter((s) => s.quantity > 0 && s.id)
    .map((s) => ({ id: s.id, label: `${p.display_name} (${v.spec}) — ${s.stock_point_name}`, qty: s.quantity, cost: v.cost, code: v.code, tracked: p.serial_tracking })))),
  [products]);
  const forSale = (products || []).reduce((n, p) => n + p.variants.reduce((m, v) => m + (v.total_stock || 0), 0), 0);

  const fleet = assets.filter((a) => a.status !== "retired");
  const count = (...statuses) => fleet.filter((a) => statuses.includes(a.status)).length;
  const fleetCost = fleet.reduce((n, a) => n + (a.purchase_price || 0), 0);
  const monthlyRent = fleet.filter((a) => ["rented", "reserved"].includes(a.status)).reduce((n, a) => n + (a.monthly_rent || 0), 0);

  const say = (text) => { setNote(text); setError(""); };
  const fail = (e, fields = []) => {
    const b = e.body || {};
    setError([].concat(...fields.map((f) => b[f] || []), b.detail || []).join(" ") || e.message);
  };

  const openAdd = async () => {
    setNote(""); setError(""); setEditing(null); setReturning(null);
    setAdding({ stock: "", serial: "", tag: "", purchase_price: "", monthly_rent: "" });
    if (!products) api.getAll("/products/").then(setProducts, () => setProducts([]));
  };
  const pickShelf = (id) => {
    const shelf = shelves.find((s) => s.id === Number(id));
    setAdding((f) => ({ ...f, stock: id, purchase_price: shelf?.cost ? String(shelf.cost) : f.purchase_price }));
  };
  const add = async (e) => {
    e.preventDefault();
    if (!adding.stock) return setError("Pick the laptop from Inventory.");
    if (!adding.serial.trim()) return setError("Enter the serial number on the laptop.");
    setBusy(true);
    try {
      const created = await api.post("/rental-assets/from-inventory/", {
        stock: Number(adding.stock), serial_number: adding.serial.trim(), asset_tag: adding.tag.trim(),
        purchase_price: adding.purchase_price === "" ? null : Number(adding.purchase_price),
        monthly_rent: adding.monthly_rent === "" ? null : Number(adding.monthly_rent),
      });
      onChanged(created);
      setAdding(null);
      setProducts(null); // stock changed
      say(`${created.asset_tag} (SN ${created.serial_number}) is in the rental fleet — 1 taken out of sale stock.`);
    } catch (err) {
      fail(err, ["stock", "serial_number", "asset_tag", "purchase_price", "monthly_rent"]);
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async (asset) => {
    setBusy(true);
    try {
      const updated = await api.patch(`/rental-assets/${asset.id}/`, {
        purchase_price: editing.purchase_price === "" ? null : Number(editing.purchase_price),
        monthly_rent: editing.monthly_rent === "" ? null : Number(editing.monthly_rent),
      });
      onChanged(updated);
      setEditing(null);
      say(`${asset.asset_tag} updated.`);
    } catch (err) {
      fail(err, ["purchase_price", "monthly_rent"]);
    } finally {
      setBusy(false);
    }
  };

  const start = (asset) => {
    setError(""); setNote(""); setEditing(null); setAdding(null);
    setReturning(asset.id);
    // the shop it came from, unless that shop is now inactive (not listed)
    const source = shops.find((s) => s.id === asset.source_stock_point);
    setShopId(String(source?.id || shops[0]?.id || ""));
  };

  const confirm = async (asset) => {
    setBusy(true);
    setError("");
    try {
      const updated = await api.post(`/rental-assets/${asset.id}/return-to-inventory/`, { stock_point: Number(shopId) });
      onChanged(updated);
      setReturning(null);
      setProducts(null);
      say(`${asset.asset_tag} is back in Inventory at ${updated.returned_to_name} — it can be sold now.`);
    } catch (e) {
      setError(e.body?.detail || e.body?.stock_point || e.message);
    } finally {
      setBusy(false);
    }
  };

  const shown = assets.filter((a) => showRetired || a.status !== "retired");
  const retiredCount = assets.length - fleet.length;
  const small = { fontFamily: F.body, color: C.inkSoft };
  const input = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };
  const label = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2">
          <Eyebrow>Rental devices ({fleet.length})</Eyebrow>
          <div className="flex items-center gap-2">
            {canManage && !adding && (
              <button type="button" onClick={openAdd} className="flex items-center gap-1 px-2.5 py-1.5 text-xs" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700 }}>
                <Plus size={12} /> Add laptop from inventory
              </button>
            )}
            <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button>
          </div>
        </div>

        {/* the fleet in numbers */}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {[["In rental fleet", fleet.length], ["Free to rent", count("available")], ["On rent / reserved", count("rented", "reserved")],
            ["Maintenance", count("maintenance")], ["Back on sale", retiredCount]].map(([k, v]) => (
            <div key={k} className="rounded-lg px-3 py-2" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}>
              <p className="text-[10px] uppercase" style={label}>{k}</p>
              <p className="text-lg" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{v}</p>
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-xs" style={small}>
          Fleet bought for {money(fleetCost)}{monthlyRent ? ` · rent on the laptops out now: ${money(monthlyRent)}/month` : ""}.
          Laptops in the fleet are kept out of sale stock; put a free one back in Inventory to sell it.
        </p>
        {note && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
        <ErrorNote message={error} />

        {adding && (
          <form onSubmit={add} className="mt-3 rounded-xl p-3" style={{ border: `1px solid ${C.stamp}`, backgroundColor: C.slip2 }}>
            <p className="text-[10px] uppercase" style={label}>Add a laptop from inventory {products ? `· ${forSale} for sale in Inventory` : ""}</p>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="text-xs sm:col-span-2" style={small}>Laptop (product and shop)
                <select value={adding.stock} onChange={(e) => pickShelf(e.target.value)} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input}>
                  <option value="">{products ? (shelves.length ? "Pick from what's in stock" : "Nothing in stock in Inventory") : "Loading inventory…"}</option>
                  {shelves.map((s) => <option key={s.id} value={s.id}>{s.label} · {s.qty} in stock</option>)}
                </select>
              </label>
              <label className="text-xs" style={small}>Serial number *
                <input value={adding.serial} onChange={(e) => setAdding({ ...adding, serial: e.target.value })} maxLength={80} placeholder="On the laptop's sticker" className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
              </label>
              <label className="text-xs" style={small}>Asset tag (optional)
                <input value={adding.tag} onChange={(e) => setAdding({ ...adding, tag: e.target.value })} maxLength={48} placeholder="Blank = next AST number" className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
              </label>
              <label className="text-xs" style={small}>Purchase price (₹)
                <input value={adding.purchase_price} inputMode="numeric" onChange={(e) => setAdding({ ...adding, purchase_price: digits(e.target.value) })} placeholder="What it cost" className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
              </label>
              <label className="text-xs" style={small}>Rent per month (₹)
                <input value={adding.monthly_rent} inputMode="numeric" onChange={(e) => setAdding({ ...adding, monthly_rent: digits(e.target.value) })} placeholder="e.g. 2500" className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
              </label>
            </div>
            <p className="mt-1.5 text-[11px]" style={small}>Purchase price starts at the product's cost in Inventory. The rent per month is filled in when this laptop is picked for an agreement (it can still be changed there).</p>
            <div className="mt-2 flex items-center gap-2">
              <button type="submit" disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700, opacity: busy ? 0.6 : 1 }}>{busy ? "Adding…" : "Add to rental fleet"}</button>
              <button type="button" onClick={() => { setAdding(null); setError(""); }} className="text-xs underline" style={small}>Cancel</button>
            </div>
          </form>
        )}

        <div className="mt-3 space-y-1.5">
          {shown.map((a) => {
            const free = ["available", "maintenance"].includes(a.status);
            const isEditing = editing?.id === a.id;
            return (
              <div key={a.id} className="rounded-xl px-3 py-2" style={{ backgroundColor: C.slip2 }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 text-sm" style={{ fontFamily: F.body, color: C.ink }}>
                    <b style={{ fontFamily: F.mono }}>{a.asset_tag}</b> · {a.brand} {a.model_name}
                    <span className="ml-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>SN {a.serial_number}</span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <Pill color={STATUS_COLOR[a.status] || C.inkSoft}>{a.status === "retired" && a.returned_to_stock_at ? "Back in inventory" : STATUS_LABEL[a.status] || a.status}</Pill>
                    <button onClick={() => setHistoryOf(a.id)} title="Customers, problems and repairs for this laptop" className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body, fontWeight: 600 }}>
                      <History size={11} /> Device
                    </button>
                    {canManage && free && a.variant && returning !== a.id && (
                      <button onClick={() => start(a)} title="Put it back in Inventory so it can be sold" className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontFamily: F.body, fontWeight: 600 }}>
                        <Undo2 size={11} /> Back to inventory for sale
                      </button>
                    )}
                  </span>
                </div>

                {a.status !== "retired" && !isEditing && (
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs" style={small}>
                    <span>Bought for <b style={{ fontFamily: F.mono, color: C.ink }}>{a.purchase_price != null ? money(a.purchase_price) : "—"}</b></span>
                    <span>Rent <b style={{ fontFamily: F.mono, color: C.ink }}>{a.monthly_rent ? `${money(a.monthly_rent)}/month` : "not set"}</b></span>
                    {a.source_stock_point_name && <span>From {a.source_stock_point_name}</span>}
                    {canManage && (
                      <button type="button" onClick={() => { setNote(""); setError(""); setEditing({ id: a.id, purchase_price: a.purchase_price ?? "", monthly_rent: a.monthly_rent ?? "" }); }}
                        className="flex items-center gap-1 underline" style={{ color: C.stamp, fontWeight: 600 }}>
                        <PencilLine size={11} /> Edit price & rent
                      </button>
                    )}
                  </p>
                )}
                {isEditing && (
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <label className="text-xs" style={small}>Purchase price (₹)
                      <input value={editing.purchase_price} inputMode="numeric" onChange={(e) => setEditing({ ...editing, purchase_price: digits(e.target.value) })} className="mt-1 block w-32 px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
                    </label>
                    <label className="text-xs" style={small}>Rent per month (₹)
                      <input value={editing.monthly_rent} inputMode="numeric" onChange={(e) => setEditing({ ...editing, monthly_rent: digits(e.target.value) })} className="mt-1 block w-32 px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
                    </label>
                    <button onClick={() => saveEdit(a)} disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Save"}</button>
                    <button onClick={() => setEditing(null)} className="text-xs underline" style={small}>Cancel</button>
                  </div>
                )}

                {a.status === "retired" && a.returned_to_stock_at && (
                  <p className="mt-0.5 text-xs" style={small}>Back in Inventory at {a.returned_to_name} since {fmt(a.returned_to_stock_at)} — for sale</p>
                )}
                {canManage && free && !a.variant && (
                  <p className="mt-0.5 text-xs" style={small}>Registered by hand, not from Inventory — add the product in Inventory to sell it.</p>
                )}
                {returning === a.id && (
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <label className="text-xs" style={{ display: "block", ...small }}>Add to stock at
                      <select value={shopId} onChange={(e) => setShopId(e.target.value)} className="mt-1 block px-2 py-1.5 text-sm outline-none" style={input}>
                        {shops.map((s) => <option key={s.id} value={s.id}>{s.name}{s.id === a.source_stock_point ? " (came from here)" : ""}</option>)}
                      </select>
                    </label>
                    <button onClick={() => confirm(a)} disabled={busy || !shopId} className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>
                      <PackageOpen size={12} /> {busy ? "Returning…" : "Put back on sale"}
                    </button>
                    <button onClick={() => setReturning(null)} className="text-xs underline" style={small}>Cancel</button>
                  </div>
                )}
              </div>
            );
          })}
          {!shown.length && <p className="text-sm" style={small}>No rental devices yet{canManage ? " — add one from inventory above." : "."}</p>}
        </div>
        {retiredCount > 0 && (
          <button onClick={() => setShowRetired(!showRetired)} className="mt-3 text-xs underline" style={small}>
            {showRetired ? "Hide" : "Show"} {retiredCount} laptop{retiredCount > 1 ? "s" : ""} put back on sale
          </button>
        )}
      </div>
      {historyOf && <DeviceHistoryModal assetId={historyOf} onClose={() => setHistoryOf(null)} />}
    </div>
  );
}
