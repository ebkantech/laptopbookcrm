import { useEffect, useState } from "react";
import { PackageOpen, Undo2, X } from "lucide-react";
import { C, F, fmt } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";

const STATUS_COLOR = { available: C.green, reserved: C.amber, rented: C.blue, maintenance: C.amber, retired: C.inkSoft };

/*
 * The rental fleet: every device, where it is, and -- for a free unit
 * that came out of Inventory -- a way to put it back on sale. It goes
 * back as +1 in a shop's stock of that product and leaves the fleet
 * (its rental history is kept).
 */
export default function RentalDevicesModal({ assets, canManage, onClose, onChanged }) {
  const [shops, setShops] = useState([]);
  const [returning, setReturning] = useState(null); // asset id
  const [shopId, setShopId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [showRetired, setShowRetired] = useState(false);

  useEffect(() => { if (canManage) api.getAll("/stock-points/").then(setShops); }, [canManage]);

  const start = (asset) => {
    setError("");
    setNote("");
    setReturning(asset.id);
    setShopId(String(asset.source_stock_point || shops[0]?.id || ""));
  };

  const confirm = async (asset) => {
    setBusy(true);
    setError("");
    try {
      const updated = await api.post(`/rental-assets/${asset.id}/return-to-inventory/`, { stock_point: Number(shopId) });
      onChanged(updated);
      setReturning(null);
      setNote(`${asset.asset_tag} is back in stock at ${updated.returned_to_name}.`);
    } catch (e) {
      setError(e.body?.detail || e.body?.stock_point || e.message);
    } finally {
      setBusy(false);
    }
  };

  const shown = assets.filter((a) => showRetired || a.status !== "retired");
  const retiredCount = assets.length - assets.filter((a) => a.status !== "retired").length;
  const small = { fontFamily: F.body, color: C.inkSoft };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <Eyebrow>Rental devices ({assets.length - retiredCount})</Eyebrow>
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        <p className="mt-1 text-xs" style={small}>A free device that came from Inventory can go back on sale — it's added to that shop's stock and leaves the rental fleet.</p>
        {note && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
        <ErrorNote message={error} />

        <div className="mt-3 space-y-1.5">
          {shown.map((a) => {
            const free = ["available", "maintenance"].includes(a.status);
            return (
              <div key={a.id} className="px-3 py-2" style={{ backgroundColor: C.slip2 }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>
                    <b style={{ fontFamily: F.mono }}>{a.asset_tag}</b> · {a.brand} {a.model_name}
                    <span className="ml-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>SN {a.serial_number}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Pill color={STATUS_COLOR[a.status] || C.inkSoft}>{a.status === "retired" && a.returned_to_stock_at ? "back in inventory" : a.status}</Pill>
                    {canManage && free && a.variant && returning !== a.id && (
                      <button onClick={() => start(a)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontFamily: F.body, fontWeight: 600 }}>
                        <Undo2 size={11} /> Back to inventory
                      </button>
                    )}
                  </span>
                </div>
                {a.status === "retired" && a.returned_to_stock_at && (
                  <p className="mt-0.5 text-xs" style={small}>Returned to {a.returned_to_name} on {fmt(a.returned_to_stock_at)}</p>
                )}
                {canManage && free && !a.variant && (
                  <p className="mt-0.5 text-xs" style={small}>Registered by hand, not from Inventory — add the product in Inventory to sell it.</p>
                )}
                {returning === a.id && (
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <label className="text-xs" style={{ display: "block", ...small }}>Add to stock at
                      <select value={shopId} onChange={(e) => setShopId(e.target.value)} className="mt-1 block px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }}>
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
          {!shown.length && <p className="text-sm" style={small}>No rental devices yet.</p>}
        </div>
        {retiredCount > 0 && (
          <button onClick={() => setShowRetired(!showRetired)} className="mt-3 text-xs underline" style={small}>
            {showRetired ? "Hide" : "Show"} {retiredCount} retired / returned device{retiredCount > 1 ? "s" : ""}
          </button>
        )}
      </div>
    </div>
  );
}
