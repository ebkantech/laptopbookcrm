import { useState } from "react";
import { Truck } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, todayISO } from "../../lib/theme";
import { ErrorNote } from "../../components/Atoms";
import { loadSuppliers } from "../../components/parties/suppliers";

const digits = (v) => String(v ?? "").replace(/\D/g, "");

/*
 * Set the supplier on stock that's already here (or already sold): pick the
 * units by serial number -- or, for a product without serial numbers, how
 * many -- and the bill they came on. It's what lets the supplier comparison
 * include stock bought before suppliers were recorded.
 */
export default function SupplierTagPanel({ product, variant }) {
  const [form, setForm] = useState(null);
  const [suppliers, setSuppliers] = useState([]);
  const [units, setUnits] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const open = async () => {
    setError(""); setNote("");
    setForm({ supplier: "", unit_cost: variant.cost ? String(variant.cost) : "", bill_no: "", purchased_on: "", picked: [], qty: "", already_paid: true });
    try {
      const [list, untagged] = await Promise.all([loadSuppliers(), api.get(`/purchases/untagged/?variant=${variant.id}`)]);
      setSuppliers(list);
      setUnits(untagged);
    } catch (e) {
      setError(e.message);
      setUnits([]);
    }
  };
  const toggle = (sn) => setForm((f) => ({ ...f, picked: f.picked.includes(sn) ? f.picked.filter((x) => x !== sn) : [...f.picked, sn] }));

  const submit = async (e) => {
    e.preventDefault();
    const bySerial = (units || []).length > 0;
    if (!form.supplier) return setError("Choose the supplier.");
    if (!form.unit_cost) return setError("Enter the price paid per unit.");
    if (bySerial ? !form.picked.length : !form.qty) return setError(bySerial ? "Tick the units that came from this supplier." : "Enter how many units.");
    setBusy(true); setError("");
    try {
      const done = await api.post("/purchases/tag/", {
        supplier: Number(form.supplier), variant: variant.id, unit_cost: Number(form.unit_cost), bill_no: form.bill_no.trim(),
        purchased_on: form.purchased_on || null, already_paid: form.already_paid, ...(bySerial ? { serials: form.picked } : { qty: Number(form.qty) }),
      });
      setNote(`${done.qty} unit${done.qty === 1 ? "" : "s"} recorded as bought from ${done.supplier}.`);
      setForm(null);
    } catch (err) {
      const b = err.body || {};
      setError([].concat(b.serials || [], b.supplier || [], b.unit_cost || [], b.purchased_on || [], b.detail || []).join(" ") || err.message);
    } finally {
      setBusy(false);
    }
  };

  const small = { fontFamily: F.body, color: C.inkSoft };
  const input = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };
  return (
    <div className="mt-2">
      {!form && (
        <button type="button" onClick={open} className="flex items-center gap-1 px-2 py-1 text-[11px]" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body, fontWeight: 600 }}>
          <Truck size={11} /> Set supplier for stock already held
        </button>
      )}
      {note && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
      {form && (
        <form onSubmit={submit} className="rounded-lg p-2.5" style={{ border: `1px solid ${C.stamp}`, backgroundColor: C.slip2 }}>
          <p className="text-[10px] uppercase" style={{ ...small, fontWeight: 700, letterSpacing: "0.08em" }}>Set supplier · {product.display_name} ({variant.spec})</p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-4">
            <label className="text-xs sm:col-span-2" style={small}>Supplier *
              <select value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input}>
                <option value="">{suppliers.length ? "Choose" : "No suppliers yet — add one in Parties (type Supplier)"}</option>
                {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label className="text-xs" style={small}>Price paid / unit (₹) *
              <input value={form.unit_cost} inputMode="numeric" onChange={(e) => setForm({ ...form, unit_cost: digits(e.target.value) })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
            </label>
            <label className="text-xs" style={small}>Bill no.
              <input value={form.bill_no} maxLength={60} onChange={(e) => setForm({ ...form, bill_no: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input} />
            </label>
            <label className="text-xs" style={small}>Bought on
              <input type="date" value={form.purchased_on} max={todayISO()} onChange={(e) => setForm({ ...form, purchased_on: e.target.value })} className="mt-1 block w-full px-2 py-1.5 text-sm outline-none" style={input} />
            </label>
          </div>
          {units === null ? <p className="mt-2 text-xs" style={small}>Loading units…</p> : units.length ? (
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs" style={small}>
                <span>Units with no supplier yet ({units.length}) — tick the ones from this bill:</span>
                <button type="button" className="underline" style={{ color: C.stamp }} onClick={() => setForm((f) => ({ ...f, picked: f.picked.length === units.length ? [] : units.map((u) => u.serial_number) }))}>
                  {form.picked.length === units.length ? "Clear all" : "Tick all"}
                </button>
              </div>
              <div className="mt-1 grid max-h-40 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
                {units.map((u) => (
                  <label key={u.serial_number} className="flex items-center gap-2 px-2 py-1 text-xs" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}`, fontFamily: F.mono, color: C.ink }}>
                    <input type="checkbox" checked={form.picked.includes(u.serial_number)} onChange={() => toggle(u.serial_number)} />
                    {u.serial_number}<span className="ml-auto" style={{ fontFamily: F.body, color: C.inkSoft }}>{u.status_label} · {u.store}</span>
                  </label>
                ))}
              </div>
            </div>
          ) : (
            <label className="mt-2 block text-xs" style={small}>No serial-numbered units without a supplier — how many units came on this bill?
              <input value={form.qty} inputMode="numeric" onChange={(e) => setForm({ ...form, qty: digits(e.target.value) })} className="mt-1 block w-28 px-2 py-1.5 text-sm outline-none" style={{ ...input, fontFamily: F.mono }} />
            </label>
          )}
          <label className="mt-2 flex items-center gap-2 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
            <input type="checkbox" checked={form.already_paid} onChange={(e) => setForm({ ...form, already_paid: e.target.checked })} />
            Already paid for — nothing owed to the supplier (untick if this bill is still to be paid)
          </label>
          <ErrorNote message={error} />
          <div className="mt-2 flex items-center gap-2">
            <button type="submit" disabled={busy} className="px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Save supplier"}</button>
            <button type="button" onClick={() => { setForm(null); setError(""); }} className="text-xs underline" style={small}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
