import { useEffect, useMemo, useRef, useState } from "react";
import { Package, Plus, Trash2, X } from "lucide-react";

import { api } from "../../lib/api";
import { C, todayISO } from "../../lib/theme";
import { ErrorNote, Eyebrow } from "../Atoms";
import NewRentalCustomer from "./NewRentalCustomer";
import CustomerIdPanel from "../parties/CustomerIdPanel";
import { kycVerified } from "./onboardingModel";
import { ASSET_LIMITS, LIMITS, describeServerError, validateAgreement, validateAssetDraft, validateInventoryPick } from "./agreementValidation";


// inline message under a field (only rendered when there is one)
function FieldError({ id, message }) {
  if (!message) return null;
  return <p id={id} role="alert" className="mt-1 text-xs" style={{ color: C.carbon, fontWeight: 600 }}>{message}</p>;
}
const boxStyle = (message) => ({ border: `1px solid ${message ? C.carbon : C.rule}`, color: C.ink });

const emptyAsset = { asset_tag: "", serial_number: "", brand: "", model_name: "" };

export default function RentalAgreementModal({ parties, initialAssets, initialParty = "", renewing = null, canAddCustomer = false, onCustomerCreated, onCreated, onClose }) {
  const [addingCustomer, setAddingCustomer] = useState(false);
  // Renewal: the finished agreement's devices come back to stock when this one is saved, so offer them as available.
  const [assets, setAssets] = useState(() => (renewing
    ? [...initialAssets.filter((a) => !renewing.lines.some((l) => l.asset_id === a.id)), ...renewing.lines.map((l) => ({ ...l.asset, status: "available" }))]
    : initialAssets));
  const [party, setParty] = useState(initialParty ? String(initialParty) : "");   // re-agreement: customer pre-chosen
  const [start, setStart] = useState(todayISO());
  const [tenureMonths, setTenureMonths] = useState(renewing ? String(renewing.tenure_months) : "1");
  const [billingCycle, setBillingCycle] = useState(renewing ? String(renewing.payment_interval_months || 1) : "1");
  const [autoInvoice, setAutoInvoice] = useState(renewing ? renewing.auto_invoice !== false : true);
  const [terms, setTerms] = useState("");
  const [lines, setLines] = useState(renewing ? renewing.lines.map((l) => ({ asset_id: String(l.asset_id), monthly_fee: String(l.monthly_fee) })) : [{ asset_id: "", monthly_fee: "" }]);
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
  const [draftErrors, setDraftErrors] = useState({}); // per-field messages for the two device sub-forms

  const [idDocuments, setIdDocuments] = useState(null);
  const selectedParty = parties.find((p) => String(p.id) === String(party));
  const kycReady = kycVerified(idDocuments, selectedParty?.customer_classification);

  const availableAssets = useMemo(() => assets.filter((asset) => asset.status === "available"), [assets]);

  // Validation runs live, but errors are only shown once the user has tried to save.
  const [submitted, setSubmitted] = useState(false);
  const [serverFields, setServerFields] = useState({});
  const errorRef = useRef(null);
  const assetLabel = (id) => assets.find((a) => String(a.id) === String(id))?.asset_tag || "Device";
  const check = useMemo(
    () => validateAgreement({ party, start, tenure: tenureMonths, billingCycle, autoInvoice, terms, lines }, { today: todayISO(), parties, assetLabel }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [party, start, tenureMonths, billingCycle, autoInvoice, terms, lines, parties, assets],
  );
  const shown = submitted ? check.errors : { lines: lines.map(() => ({})) };
  const fieldError = (key, serverKey) => shown[key] || serverFields[serverKey];
  const lineError = (index, key) => shown.lines[index]?.[key]
    || [].concat(serverFields.lines?.[index]?.[key === "asset" ? "asset_id" : "monthly_fee"] || []).join(" ");
  // editing anything clears the server's complaint about it
  useEffect(() => { setServerFields({}); }, [party, start, tenureMonths, billingCycle, terms, lines]);
  useEffect(() => { setDraftErrors({}); }, [assetDraft, invSerial, invTag, stockId]);
  useEffect(() => { if (error) errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [error]);
  // a stray click on the backdrop must not throw away a half-filled agreement
  const dirty = !!renewing || !!((party && party !== String(initialParty || "")) || terms || lines.some((l) => l.asset_id || l.monthly_fee) || tenureMonths !== "1" || billingCycle !== "1" || start !== todayISO());
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
    const draftCheck = validateAssetDraft(assetDraft);
    setDraftErrors(draftCheck.errors);
    if (draftCheck.summary.length) {
      setError(draftCheck.summary.join(" "));
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
        const { message, fields } = describeServerError(requestError);
        setDraftErrors(fields);
        setError(message);
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
      const [products, open] = await Promise.all([api.getAll("/products/?category=laptop"), api.getAll("/stock-points/?active=1")]);
      // units can't leave an inactive shop's stock for a new rental
      const openSlugs = new Set(open.map((sp) => sp.slug));
      // one row per (variant, shop) that actually has units on the shelf
      setStockRows(products.flatMap((p) => p.variants.flatMap((v) => v.stock
        .filter((s) => s.quantity > 0 && openSlugs.has(s.stock_point))
        .map((s) => ({ id: s.id, label: `${p.display_name} · ${v.spec}`, code: v.code, shop: s.stock_point_name || s.stock_point, qty: s.quantity, location: s.location })))));
    } catch (e) {
      setError(e.message);
    }
  };

  const takeFromInventory = async () => {
    const pick = validateInventoryPick({ stockId, serial: invSerial, tag: invTag });
    setDraftErrors(pick.errors);
    if (pick.summary.length) {
      setError(pick.summary.join(" "));
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
      const { message, fields } = describeServerError({ ...requestError, status: requestError.status, body: Object.fromEntries(Object.entries(requestError.body || {}).filter(([k]) => k !== "existing_asset")) });
      setDraftErrors(fields);
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setSubmitted(true);
    if (!check.valid) {
      setError(
        <>
          <b>{check.errors.summary.length === 1 ? "Fix this before saving:" : `Fix these ${check.errors.summary.length} things before saving:`}</b>
          <ul className="mt-1 list-disc pl-4 font-normal">{check.errors.summary.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </>,
      );
      return;
    }
    const selectedLines = lines.filter((line) => line.asset_id);
    setBusy(true);
    setError("");
    try {
      const created = await api.post("/rentals/create-agreement/", {
        party: Number(party),
        start,
        tenure_months: Number(tenureMonths),
        payment_interval_months: Number(billingCycle),
        auto_invoice: autoInvoice,
        terms: terms.trim(),
        lines: selectedLines.map((line) => ({ asset_id: Number(line.asset_id), monthly_fee: Number(line.monthly_fee) })),
        ...(renewing ? { renews: renewing.id } : {}),
      });
      onCreated(created);
    } catch (requestError) {
      const { message, fields } = describeServerError(requestError);
      setServerFields(fields);
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto p-4" style={{ backgroundColor: "rgba(4,9,18,0.72)" }} onClick={() => { if (!dirty && !busy) onClose(); }}>
      <form noValidate onSubmit={submit} className="my-auto w-full max-w-2xl p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3"><div><Eyebrow>New rental agreement</Eyebrow><p className="mt-1 text-xs" style={{ color: C.inkSoft }}>One device becomes Single; two or more become Bulk automatically. Next you'll record each device's condition, photos, accessories and warranty for the customer to approve.</p></div><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={17} /></button></div>
        {renewing && (
          <p className="mt-3 p-2 text-xs" data-testid="renewal-note" style={{ backgroundColor: `${C.green}12`, border: `1px solid ${C.green}55`, color: C.ink }}>
            Re-agreement for {renewing.party_name}: the devices, rates, tenure and payment cycle of {renewing.agreement_code} are filled in — change anything you need.
            Saving closes {renewing.agreement_code} and hands its devices to this new agreement.
          </p>
        )}
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <label className="text-xs" style={{ color: C.inkSoft }}>Customer<select value={party} disabled={!!renewing} aria-invalid={!!fieldError("party", "party")} aria-describedby="err-party" onChange={(event) => setParty(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(fieldError("party", "party"))}><option value="">Choose customer</option>{parties.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.customer_classification || "individual"}</option>)}</select><FieldError id="err-party" message={fieldError("party", "party")} /></label>
          <label className="text-xs" style={{ color: C.inkSoft }}>Start date<input type="date" value={start} aria-invalid={!!fieldError("start", "start")} aria-describedby="err-start" onChange={(event) => setStart(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(fieldError("start", "start"))} /><FieldError id="err-start" message={fieldError("start", "start")} /></label>
          <label className="text-xs" style={{ color: C.inkSoft }}>Tenure (months)<input type="number" inputMode="numeric" min="1" max={LIMITS.tenureMax} step="1" value={tenureMonths} aria-invalid={!!fieldError("tenure", "tenure_months")} aria-describedby="err-tenure" onChange={(event) => setTenureMonths(event.target.value)} className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(fieldError("tenure", "tenure_months"))} /><FieldError id="err-tenure" message={fieldError("tenure", "tenure_months")} /></label>
        </div>
        {canAddCustomer && !renewing && !addingCustomer && (
          <button type="button" onClick={() => setAddingCustomer(true)} className="mt-2 flex items-center gap-1 text-xs underline" style={{ color: C.stamp, fontWeight: 600 }}><Plus size={12} /> Add a new rental customer</button>
        )}
        {addingCustomer && (
          <NewRentalCustomer parties={parties} onCancel={() => setAddingCustomer(false)}
            onCreated={(created, { existing } = {}) => { if (!existing) onCustomerCreated?.(created); setParty(String(created.id)); setAddingCustomer(false); }} />
        )}
        {/* KYC comes first: the server refuses an agreement until the customer's IDs are verified */}
        {party && <CustomerIdPanel key={party} partyId={party} canManage required onDocuments={setIdDocuments} />}
        {party && (
          <p role="status" className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ color: kycReady ? C.inkSoft : C.carbon, backgroundColor: C.slip2 }}>
            {kycReady
              ? `Saving raises ${renewing ? "one month's advance rent" : "a security deposit and one month's advance rent, each equal to one month's rent"}.`
              : selectedParty?.customer_classification === "individual" ? "Verify the customer's Aadhaar and PAN to create this agreement." : "Verify the customer's PAN to create this agreement."}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-2">
          <label className="text-xs" style={{ color: C.inkSoft }}>Recurring payment
            <select value={billingCycle} aria-invalid={!!fieldError("billingCycle", "payment_interval_months")} onChange={(event) => setBillingCycle(event.target.value)} className="mt-1 block bg-transparent p-2 text-sm" style={boxStyle(fieldError("billingCycle", "payment_interval_months"))}>
              <option value="1">Every month</option><option value="3">Every 3 months</option><option value="6">Every 6 months</option><option value="12">Every 12 months</option>
            </select>
            <FieldError message={fieldError("billingCycle", "payment_interval_months")} />
          </label>
          <label className="flex items-center gap-1.5 pb-2 text-xs" style={{ color: C.inkSoft }}>
            <input type="checkbox" checked={autoInvoice} onChange={(event) => setAutoInvoice(event.target.checked)} />
            Send each invoice to the client automatically before it is due
          </label>
        </div>
        {check.warnings.length > 0 && (
          <div role="status" className="mt-3 space-y-1 rounded-xl px-3 py-2 text-xs" style={{ border: `1px solid ${C.amber}88`, backgroundColor: `${C.amber}12`, color: C.ink }}>
            {check.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
          </div>
        )}
        <div className="mt-5 flex items-center justify-between"><Eyebrow>Devices · {selectedCount >= 2 ? "Bulk" : "Single"}</Eyebrow><div className="flex items-center gap-3"><button type="button" onClick={openInventory} className="flex items-center gap-1 text-xs" style={{ color: C.orange, fontWeight: 600 }}><Package size={12} /> Rent out from inventory</button><button type="button" onClick={() => { setShowAssetForm((value) => !value); setShowInventory(false); }} className="flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Register device not in inventory</button></div></div>
        {showInventory && (
          <div className="mt-2 space-y-2 p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}>
            <p className="text-xs" style={{ color: C.inkSoft }}>Pick a laptop that's in stock. One unit leaves that shop's sale stock and joins the rental fleet.</p>
            {!stockRows ? <p className="text-xs" style={{ color: C.inkSoft }}>Loading inventory…</p> : (
              <>
                <input value={stockQuery} onChange={(e) => setStockQuery(e.target.value)} placeholder="Search product, spec or shop" className="w-full bg-transparent p-2 text-sm" style={{ border: `1px solid ${C.rule}`, color: C.ink }} />
                <select value={stockId} aria-invalid={!!draftErrors.stock} onChange={(e) => setStockId(e.target.value)} size={Math.min(6, Math.max(2, stockRows.length))} className="w-full bg-transparent p-1 text-sm" style={boxStyle(draftErrors.stock)}>
                  {stockRows
                    .filter((r) => !stockQuery.trim() || `${r.label} ${r.code} ${r.shop}`.toLowerCase().includes(stockQuery.trim().toLowerCase()))
                    .map((r) => <option key={r.id} value={r.id}>{r.label} — {r.shop} ({r.qty} in stock{r.location ? `, ${r.location}` : ""})</option>)}
                </select>
                <FieldError message={draftErrors.stock} />
                {!stockRows.length && <p className="text-xs" style={{ color: C.carbon }}>Nothing is in stock in Inventory right now.</p>}
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Serial number of this unit *<input value={invSerial} maxLength={ASSET_LIMITS.serial_number + 20} aria-invalid={!!draftErrors.serial_number} onChange={(e) => setInvSerial(e.target.value)} placeholder="from the label under the laptop" className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(draftErrors.serial_number)} /><FieldError message={draftErrors.serial_number} /></label>
                  <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Asset tag (optional)<input value={invTag} maxLength={ASSET_LIMITS.asset_tag + 20} aria-invalid={!!draftErrors.asset_tag} onChange={(e) => setInvTag(e.target.value)} placeholder="blank = generate AST-####" className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(draftErrors.asset_tag)} /><FieldError message={draftErrors.asset_tag} /></label>
                </div>
                <button type="button" disabled={busy} onClick={takeFromInventory} className="w-full p-2 text-xs" style={{ backgroundColor: C.carbon, color: C.onAccent }}>{busy ? "Taking from stock…" : "Take 1 from stock and add to this agreement"}</button>
              </>
            )}
          </div>
        )}
        {showAssetForm && <div className="mt-2 grid gap-2 p-3 sm:grid-cols-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
          {[["asset_tag", "Asset tag (optional)", "Unique sticker ID, e.g. AST-0042 — blank = generate"], ["serial_number", "Serial number *", "From the label under the laptop"], ["brand", "Brand *", "e.g. Apple"], ["model_name", "Model *", "e.g. MacBook Air M2 2022"]].map(([key, label, hint]) => (
            <label key={key} className="text-xs" style={{ display: "block", color: C.inkSoft }}>{label}
              <input value={assetDraft[key]} maxLength={ASSET_LIMITS[key] + 20} aria-invalid={!!draftErrors[key]} onChange={(event) => setAssetDraft((draft) => ({ ...draft, [key]: event.target.value }))} placeholder={hint} className="mt-1 w-full bg-transparent p-2 text-sm" style={boxStyle(draftErrors[key])} /><FieldError message={draftErrors[key]} />
            </label>
          ))}
          <button type="button" disabled={busy} onClick={addAsset} className="p-2 text-xs sm:col-span-2" style={{ backgroundColor: C.carbon, color: C.onAccent }}>Save asset and select it</button>
          {existing && existing.status === "available" && (
            <button type="button" onClick={() => selectAsset(existing)} className="p-2 text-xs sm:col-span-2" style={{ border: `1px solid ${C.green}`, color: C.green, fontWeight: 600 }}>Use {existing.asset_tag} on this agreement</button>
          )}
        </div>}
        <div className="mt-2 space-y-2">{lines.map((line, index) => <div key={index}><div className="grid grid-cols-[minmax(0,1fr)_130px_32px] items-start gap-2"><select value={line.asset_id} aria-label={`Device ${index + 1}`} aria-invalid={!!lineError(index, "asset")} onChange={(event) => updateLine(index, "asset_id", event.target.value)} className="w-full min-w-0 truncate bg-transparent p-2 text-sm" style={boxStyle(lineError(index, "asset"))}><option value="">{availableAssets.length ? "Choose an available rental device" : "No free rental devices — rent one out from inventory above"}</option>{availableAssets.map((asset) => <option key={asset.id} value={asset.id} disabled={lines.some((other, position) => position !== index && other.asset_id === String(asset.id))}>{asset.asset_tag} · {asset.brand} {asset.model_name} · {asset.serial_number}</option>)}</select><input type="number" inputMode="numeric" min="1" max={LIMITS.feeMax} step="1" aria-label={`Monthly fee for device ${index + 1}`} aria-invalid={!!lineError(index, "fee")} value={line.monthly_fee} onChange={(event) => updateLine(index, "monthly_fee", event.target.value)} placeholder="₹ / month" className="w-full min-w-0 bg-transparent p-2 text-sm" style={boxStyle(lineError(index, "fee"))} /><button type="button" className="flex h-9 w-8 shrink-0 items-center justify-center" aria-label={`Remove device ${index + 1}`} disabled={lines.length === 1} onClick={() => setLines((current) => current.filter((_, position) => position !== index))}><Trash2 size={15} /></button></div><FieldError message={lineError(index, "asset")} /><FieldError message={lineError(index, "fee")} /></div>)}<FieldError message={shown.devices} /></div>
        <button type="button" onClick={() => setLines((current) => [...current, { asset_id: "", monthly_fee: "" }])} className="mt-2 flex items-center gap-1 text-xs" style={{ color: C.orange }}><Plus size={12} /> Add another device</button>
        <label className="mt-4 block text-xs" style={{ color: C.inkSoft }}>Terms (optional)<textarea value={terms} maxLength={LIMITS.termsMax + 200} aria-invalid={!!fieldError("terms", "terms")} onChange={(event) => setTerms(event.target.value)} rows={3} className="mt-1 w-full resize-none bg-transparent p-2 text-sm" style={boxStyle(fieldError("terms", "terms"))} /><span className="mt-0.5 flex justify-between text-xs"><FieldError message={fieldError("terms", "terms")} /><span style={{ marginLeft: "auto", color: terms.length > LIMITS.termsMax ? C.carbon : C.inkSoft }}>{terms.length}/{LIMITS.termsMax}</span></span></label>
        <div ref={errorRef}><ErrorNote message={error} /></div>
        <button disabled={busy || !kycReady} className="mt-4 w-full py-3 text-sm disabled:cursor-not-allowed" style={{ backgroundColor: C.green, color: C.onAccent, opacity: busy || !kycReady ? 0.65 : 1 }}>{busy ? "Saving…" : `Create ${selectedCount >= 2 ? "Bulk" : "Single"} agreement`}</button>
      </form>
    </div>
  );
}
