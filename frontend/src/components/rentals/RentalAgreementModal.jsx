import { useMemo, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";

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
        <div className="mt-5 flex items-center justify-between"><Eyebrow>Devices · {selectedCount >= 2 ? "Bulk" : "Single"}</Eyebrow><button type="button" onClick={() => setShowAssetForm((value) => !value)} className="flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Register new asset</button></div>
        {showAssetForm && <div className="mt-2 grid gap-2 p-3 sm:grid-cols-2" style={{ backgroundColor: C.slip2 }}>
          {[["asset_tag", "Asset tag (blank = auto)"], ["serial_number", "Serial number"], ["brand", "Brand"], ["model_name", "Model"]].map(([key, label]) => <input key={key} value={assetDraft[key]} onChange={(event) => setAssetDraft((draft) => ({ ...draft, [key]: event.target.value }))} placeholder={label} className="bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} />)}
          <button type="button" disabled={busy} onClick={addAsset} className="p-2 text-xs sm:col-span-2" style={{ backgroundColor: C.carbon, color: C.onAccent }}>Save asset and select it</button>
          {existing && existing.status === "available" && (
            <button type="button" onClick={() => selectAsset(existing)} className="p-2 text-xs sm:col-span-2" style={{ border: `1px solid ${C.green}`, color: C.green, fontWeight: 600 }}>Use {existing.asset_tag} on this agreement</button>
          )}
        </div>}
        <div className="mt-2 space-y-2">{lines.map((line, index) => <div key={index} className="grid grid-cols-[1fr_130px_32px] gap-2"><select value={line.asset_id} onChange={(event) => updateLine(index, "asset_id", event.target.value)} className="bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }}><option value="">Choose available asset</option>{availableAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.brand} {asset.model_name} · {asset.serial_number}</option>)}</select><input type="number" min="0" value={line.monthly_fee} onChange={(event) => updateLine(index, "monthly_fee", event.target.value)} placeholder="₹ / month" className="bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /><button type="button" disabled={lines.length === 1} onClick={() => setLines((current) => current.filter((_, position) => position !== index))}><Trash2 size={15} /></button></div>)}</div>
        <button type="button" onClick={() => setLines((current) => [...current, { asset_id: "", monthly_fee: "" }])} className="mt-2 flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Add another device</button>
        <label className="mt-4 block text-xs" style={{ color: C.inkSoft }}>Terms (optional)<textarea value={terms} onChange={(event) => setTerms(event.target.value)} rows={3} className="mt-1 w-full resize-none bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} /></label>
        <ErrorNote message={error} />
        <button disabled={busy} className="mt-4 w-full py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent, opacity: busy ? 0.65 : 1 }}>{busy ? "Saving…" : `Create ${selectedCount >= 2 ? "Bulk" : "Single"} agreement`}</button>
      </form>
    </div>
  );
}
