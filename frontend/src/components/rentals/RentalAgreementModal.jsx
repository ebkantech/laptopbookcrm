import { useMemo, useState } from "react";
import { Package, Plus, Trash2, X } from "lucide-react";

import { api } from "../../lib/api";
import { C } from "../../lib/theme";
import { ErrorNote, Eyebrow } from "../Atoms";


const emptyAsset = { asset_tag: "", serial_number: "", brand: "", model_name: "" };

export default function RentalAgreementModal({ parties, initialAssets, onCreated, onClose }) {
  const [assets, setAssets] = useState(initialAssets);
  const [party, setParty] = useState("");
  const [start, setStart] = useState(new Date().toISOString().slice(0, 10));
  const [tenureMonths, setTenureMonths] = useState("1");
  const [terms, setTerms] = useState("");
  const [lines, setLines] = useState([{ asset_id: "", monthly_fee: "" }]);
  const [assetDraft, setAssetDraft] = useState(emptyAsset);
  const [showAssetForm, setShowAssetForm] = useState(false);
  // "Rent out from inventory": laptops in shop stock, loaded on demand
  const [showInventory, setShowInventory] = useState(false);
  const [stockRows, setStockRows] = useState(null);
  const [stockQuery, setStockQuery] = useState("");
  const [stockId, setStockId] = useState("");
  const [invSerial, setInvSerial] = useState("");
  const [invTag, setInvTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [existing, setExisting] = useState(null); // an already-registered asset matching the draft

  const availableAssets = useMemo(() => assets.filter((asset) => asset.status === "available"), [assets]);
  const selectedCount = lines.filter((line) => line.asset_id).length;

  const updateLine = (index, key, value) => {
    setLines((current) => current.map((line, position) => position === index ? { ...line, [key]: value } : line));
  };

  const selectAsset = (asset) => {
    setAssets((current) => (current.some((a) => a.id === asset.id) ? current : [...current, asset]));
    setLines((current) => {
      if (current.some((line) => line.asset_id === String(asset.id))) return current;
      const emptyIndex = current.findIndex((line) => !line.asset_id);
      if (emptyIndex < 0) return [...current, { asset_id: String(asset.id), monthly_fee: "" }];
      return current.map((line, index) => index === emptyIndex ? { ...line, asset_id: String(asset.id) } : line);
    });
    setAssetDraft(emptyAsset);
    setShowAssetForm(false);
    setExisting(null);
    setError("");
  };

  const describeExisting = (asset) => (asset.status === "available"
    ? `${asset.asset_tag} (${asset.brand} ${asset.model_name}, S/N ${asset.serial_number}) is already registered and available.`
    : `${asset.asset_tag} (${asset.brand} ${asset.model_name}, S/N ${asset.serial_number}) is already registered and currently ${asset.status} -- it can't go on a new agreement until it's returned.`);

  const addAsset = async () => {
    setExisting(null);
    if (["serial_number", "brand", "model_name"].some((key) => !assetDraft[key].trim())) {
      setError("Serial number, brand and model are required. Leave the asset tag blank to generate one.");
      return;
    }
    // catch an already-registered device before asking the server
    const same = (a, b) => a && b && a.trim().toLowerCase() === b.trim().toLowerCase();
    const match = assets.find((a) => same(a.serial_number, assetDraft.serial_number) || same(a.asset_tag, assetDraft.asset_tag));
    if (match) {
      setExisting(match);
      setError(describeExisting(match));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await api.post("/rental-assets/", assetDraft);
      setAssets((current) => [...current, created]);
      setLines((current) => {
        const emptyIndex = current.findIndex((line) => !line.asset_id);
        if (emptyIndex < 0) return [...current, { asset_id: String(created.id), monthly_fee: "" }];
        return current.map((line, index) => index === emptyIndex ? { ...line, asset_id: String(created.id) } : line);
      });
      setAssetDraft(emptyAsset);
      setShowAssetForm(false);
    } catch (requestError) {
      const body = requestError.body || {};
      if (body.existing_asset) {
        const asset = { ...body.existing_asset, id: Number(body.existing_asset.id) };
        setExisting(asset);
        setError(describeExisting(asset));
      } else {
        setError(Object.values(body).flat().join(" ") || requestError.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const openInventory = async () => {
    setShowInventory((v) => !v);
    setShowAssetForm(false);
    if (stockRows) return;
    try {
      const products = await api.getAll("/products/");
      // one row per (variant, shop) that actually has units on the shelf
      setStockRows(products.flatMap((p) => p.variants.flatMap((v) => v.stock
        .filter((s) => s.quantity > 0)
        .map((s) => ({ id: s.id, label: `${p.display_name} · ${v.spec}`, code: v.code, shop: s.stock_point_name || s.stock_point, qty: s.quantity, location: s.location })))));
    } catch (e) {
      setError(e.message);
    }
  };

  const takeFromInventory = async () => {
    if (!stockId || !invSerial.trim()) {
      setError("Pick the item and enter the serial number printed on this unit.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const asset = await api.post("/rental-assets/from-inventory/", { stock: Number(stockId), serial_number: invSerial.trim(), asset_tag: invTag.trim() });
      setStockRows((rows) => rows.map((r) => (r.id === Number(stockId) ? { ...r, qty: r.qty - 1 } : r)).filter((r) => r.qty > 0));
      selectAsset(asset);
      setShowInventory(false);
      setStockId("");
      setInvSerial("");
      setInvTag("");
    } catch (requestError) {
      const body = requestError.body || {};
      setError(Object.entries(body).filter(([k]) => k !== "existing_asset").map(([, v]) => [].concat(v).join(" ")).join(" ") || requestError.message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const selectedLines = lines.filter((line) => line.asset_id);
    if (!party || !start || !tenureMonths || !selectedLines.length || selectedLines.some((line) => line.monthly_fee === "")) {
      setError("Customer, start date, tenure, device and monthly fee are required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await api.post("/rentals/create-agreement/", {
        party: Number(party),
        start,
        tenure_months: Number(tenureMonths),
        terms: terms.trim(),
        lines: selectedLines.map((line) => ({ asset_id: Number(line.asset_id), monthly_fee: Number(line.monthly_fee) })),
      });
      onCreated(created);
    } catch (requestError) {
      setError(Object.values(requestError.body || {}).flat().join(" ") || requestError.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto p-4" style={{ backgroundColor: "rgba(4,9,18,0.72)" }} onClick={onClose}>
      <form onSubmit={submit} className="my-auto w-full max-w-2xl p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3"><div><Eyebrow>New rental agreement</Eyebrow><p className="mt-1 text-xs" style={{ color: C.inkSoft }}>One device becomes Single; two or more become Bulk automatically. Next you'll record each device's condition, photos, accessories and warranty for the customer to approve.</p></div><button type="button" onClick={onClose}><X size={17} /></button></div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <label className="text-xs" style={{ color: C.inkSoft }}>Customer<select value={party} onChange={(event) => setParty(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }}><option value="">Choose customer</option>{parties.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.customer_classification || "individual"}</option>)}</select></label>
          <label className="text-xs" style={{ color: C.inkSoft }}>Start date<input type="date" value={start} onChange={(event) => setStart(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
          <label className="text-xs" style={{ color: C.inkSoft }}>Tenure (months)<input type="number" min="1" value={tenureMonths} onChange={(event) => setTenureMonths(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
        </div>
        <div className="mt-5 flex items-center justify-between"><Eyebrow>Devices · {selectedCount >= 2 ? "Bulk" : "Single"}</Eyebrow><div className="flex items-center gap-3"><button type="button" onClick={openInventory} className="flex items-center gap-1 text-xs" style={{ color: C.orange, fontWeight: 600 }}><Package size={12} /> Rent out from inventory</button><button type="button" onClick={() => { setShowAssetForm((value) => !value); setShowInventory(false); }} className="flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Register device not in inventory</button></div></div>
        {showInventory && (
          <div className="mt-2 space-y-2 p-3" style={{ backgroundColor: C.slip2 }}>
            <p className="text-xs" style={{ color: C.inkSoft }}>Pick a laptop that's in stock. One unit leaves that shop's sale stock and joins the rental fleet.</p>
            {!stockRows ? <p className="text-xs" style={{ color: C.inkSoft }}>Loading inventory…</p> : (
              <>
                <input value={stockQuery} onChange={(e) => setStockQuery(e.target.value)} placeholder="Search product, spec or shop" className="w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} />
                <select value={stockId} onChange={(e) => setStockId(e.target.value)} size={Math.min(6, Math.max(2, stockRows.length))} className="w-full bg-transparent p-1 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }}>
                  {stockRows
                    .filter((r) => !stockQuery.trim() || `${r.label} ${r.code} ${r.shop}`.toLowerCase().includes(stockQuery.trim().toLowerCase()))
                    .map((r) => <option key={r.id} value={r.id}>{r.label} — {r.shop} ({r.qty} in stock{r.location ? `, ${r.location}` : ""})</option>)}
                </select>
                {!stockRows.length && <p className="text-xs" style={{ color: C.carbon }}>Nothing is in stock in Inventory right now.</p>}
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Serial number of this unit *<input value={invSerial} onChange={(e) => setInvSerial(e.target.value)} placeholder="from the label under the laptop" className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
                  <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Asset tag (optional)<input value={invTag} onChange={(e) => setInvTag(e.target.value)} placeholder="blank = generate AST-####" className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
                </div>
                <button type="button" disabled={busy} onClick={takeFromInventory} className="w-full p-2 text-xs" style={{ backgroundColor: C.carbon, color: C.onAccent }}>{busy ? "Taking from stock…" : "Take 1 from stock and add to this agreement"}</button>
              </>
            )}
          </div>
        )}
        {showAssetForm && <div className="mt-2 grid gap-2 p-3 sm:grid-cols-2" style={{ backgroundColor: C.slip2 }}>
          {[["asset_tag", "Asset tag (optional)", "Unique sticker ID, e.g. AST-0042 — blank = generate"], ["serial_number", "Serial number *", "From the label under the laptop"], ["brand", "Brand *", "e.g. Apple"], ["model_name", "Model *", "e.g. MacBook Air M2 2022"]].map(([key, label, hint]) => (
            <label key={key} className="text-xs" style={{ display: "block", color: C.inkSoft }}>{label}
              <input value={assetDraft[key]} onChange={(event) => setAssetDraft((draft) => ({ ...draft, [key]: event.target.value }))} placeholder={hint} className="mt-1 w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} />
            </label>
          ))}
          <button type="button" disabled={busy} onClick={addAsset} className="p-2 text-xs sm:col-span-2" style={{ backgroundColor: C.carbon, color: C.onAccent }}>Save asset and select it</button>
          {existing && existing.status === "available" && (
            <button type="button" onClick={() => selectAsset(existing)} className="p-2 text-xs sm:col-span-2" style={{ border: `1px solid ${C.green}`, color: C.green, fontWeight: 600 }}>Use {existing.asset_tag} on this agreement</button>
          )}
        </div>}
        <div className="mt-2 space-y-2">{lines.map((line, index) => <div key={index} className="grid grid-cols-[1fr_130px_32px] gap-2"><select value={line.asset_id} onChange={(event) => updateLine(index, "asset_id", event.target.value)} className="bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }}><option value="">{availableAssets.length ? "Choose an available rental device" : "No free rental devices — rent one out from inventory above"}</option>{availableAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.brand} {asset.model_name} · {asset.serial_number}</option>)}</select><input type="number" min="0" value={line.monthly_fee} onChange={(event) => updateLine(index, "monthly_fee", event.target.value)} placeholder="₹ / month" className="bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /><button type="button" disabled={lines.length === 1} onClick={() => setLines((current) => current.filter((_, position) => position !== index))}><Trash2 size={15} /></button></div>)}</div>
        <button type="button" onClick={() => setLines((current) => [...current, { asset_id: "", monthly_fee: "" }])} className="mt-2 flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Add another device</button>
        <label className="mt-4 block text-xs" style={{ color: C.inkSoft }}>Terms (optional)<textarea value={terms} onChange={(event) => setTerms(event.target.value)} rows={3} className="mt-1 w-full resize-none bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
        <ErrorNote message={error} />
        <button disabled={busy} className="mt-4 w-full py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent, opacity: busy ? 0.65 : 1 }}>{busy ? "Saving…" : `Create ${selectedCount >= 2 ? "Bulk" : "Single"} agreement`}</button>
      </form>
    </div>
  );
}
