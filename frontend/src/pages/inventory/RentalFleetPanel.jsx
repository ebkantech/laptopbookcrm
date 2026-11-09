import { useEffect, useState } from "react";
import { History, KeyRound } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";
import { ErrorNote, Pill } from "../../components/Atoms";
import DeviceHistoryModal from "../../components/rentals/DeviceHistoryModal";

const STATUS_COLOR = { available: C.green, reserved: C.amber, rented: C.blue, maintenance: C.amber };
const STATUS_LABEL = { available: "Free to rent", reserved: "Reserved", rented: "On rent", maintenance: "Maintenance" };

/*
 * One variant's rental units in Inventory. A laptop set "For rent" leaves
 * sale stock (so it can't be sold by mistake) and joins the rental fleet,
 * where it's picked for agreements. Each unit has a Device button with its
 * whole history: customers, problems raised, repairs and who did them.
 */
export default function RentalFleetPanel({ product, variant, serials, canView, canManage, onChanged }) {
  const [assets, setAssets] = useState(null);
  const [version, setVersion] = useState(0);
  const [form, setForm] = useState(null); // { stock, serial, tag }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [historyOf, setHistoryOf] = useState(null);

  useEffect(() => {
    if (!canView) return;
    api.getAll(`/rental-assets/?variant=${variant.id}`).then(setAssets, () => setAssets([]));
  }, [variant.id, canView, version]);

  const shelves = variant.stock.filter((s) => s.quantity > 0);
  const tracked = product.serial_tracking;
  const fleet = (assets || []).filter((a) => a.status !== "retired");
  const onRent = fleet.filter((a) => ["rented", "reserved"].includes(a.status)).length;
  const shelf = form && shelves.find((s) => s.id === Number(form.stock));
  // serial-numbered units on that shop's shelf, to pick from
  const shelfSerials = tracked && shelf ? (serials || []).filter((s) => s.status === "in_stock" && s.stock_point === shelf.stock_point_name) : [];

  const open = () => {
    setError(""); setNote("");
    setForm({ stock: String(shelves[0]?.id || ""), serial: "", tag: "" });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.serial.trim()) { setError("Enter the serial number on the laptop you're setting aside for rent."); return; }
    setBusy(true); setError("");
    try {
      const asset = await api.post("/rental-assets/from-inventory/", { stock: Number(form.stock), serial_number: form.serial.trim(), asset_tag: form.tag.trim() });
      setNote(`${asset.asset_tag} (SN ${asset.serial_number}) is now for rent — it's out of sale stock at ${shelf?.stock_point_name || "the shop"}.`);
      setForm(null);
      setVersion((n) => n + 1);
      onChanged();
    } catch (err) {
      const b = err.body || {};
      setError(b.serial_number || b.stock || b.asset_tag || b.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!canView) return null;
  const label = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };
  const small = { fontFamily: F.body, color: C.inkSoft };
  const input = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };

  return (
    <div className="mt-3 rounded-lg p-2.5" style={{ border: `1px dashed ${C.rule}` }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] uppercase" style={label}>
          For rent · {assets === null ? "…" : `${fleet.length} unit${fleet.length === 1 ? "" : "s"}${fleet.length ? ` (${onRent} on rent, ${fleet.length - onRent} free)` : ""}`}
        </p>
        {canManage && shelves.length > 0 && !form && (
          <button type="button" onClick={open} className="flex items-center gap-1 px-2 py-1 text-[11px]" style={{ border: `1px solid ${C.blue}`, color: C.blue, fontFamily: F.body, fontWeight: 600 }}>
            <KeyRound size={11} /> Set a unit for rent
          </button>
        )}
      </div>
      <p className="mt-0.5 text-[11px]" style={small}>Units for rent are kept out of sale stock, so they can't be sold by mistake. Put one back on sale from Rentals → Devices.</p>
      {note && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}

      {form && (
        <form onSubmit={submit} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <label className="text-xs" style={small}>From shop
            <select value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value, serial: "" })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input}>
              {shelves.map((s) => <option key={s.id} value={s.id}>{s.stock_point_name} ({s.quantity} for sale)</option>)}
            </select>
          </label>
          <label className="text-xs" style={small}>Serial number *
            {shelfSerials.length > 0 ? (
              <select value={form.serial} onChange={(e) => setForm({ ...form, serial: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }}>
                <option value="">Pick the unit</option>
                {shelfSerials.map((s) => <option key={s.serial_number} value={s.serial_number}>{s.serial_number}</option>)}
              </select>
            ) : (
              <input value={form.serial} onChange={(e) => setForm({ ...form, serial: e.target.value })} placeholder="On the laptop's sticker" maxLength={80} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
            )}
          </label>
          <label className="text-xs" style={small}>Asset tag (optional)
            <input value={form.tag} onChange={(e) => setForm({ ...form, tag: e.target.value })} placeholder="Blank = next AST number" maxLength={48} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
          </label>
          <div className="flex items-center gap-2 sm:col-span-3">
            <button type="submit" disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.blue, color: C.onAccent, fontFamily: F.body, fontWeight: 700, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Set for rent"}</button>
            <button type="button" onClick={() => { setForm(null); setError(""); }} className="text-xs underline" style={small}>Cancel</button>
          </div>
        </form>
      )}
      <ErrorNote message={error} />

      {fleet.length > 0 && (
        <ul className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2" aria-label="Rental units">
          {fleet.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}>
              <span className="min-w-0">
                <span className="block" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{a.asset_tag}</span>
                <span className="block truncate" title={a.serial_number} style={{ fontFamily: F.mono, color: C.inkSoft }}>SN {a.serial_number}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <Pill color={STATUS_COLOR[a.status] || C.inkSoft}>{STATUS_LABEL[a.status] || a.status}</Pill>
                <button type="button" onClick={() => setHistoryOf(a.id)} title="Customers, problems and repairs for this laptop" className="flex items-center gap-1 px-1.5 py-0.5 text-[11px]" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body, fontWeight: 600 }}>
                  <History size={10} /> Device
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {historyOf && <DeviceHistoryModal assetId={historyOf} onClose={() => setHistoryOf(null)} />}
    </div>
  );
}
