import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { api } from "../../lib/api";
import { money } from "../../lib/theme";
import { Alert, Dialog } from "../settings/StaffUi";
import { fromSheet, toSheet } from "./costSheet";
import "../settings/staff.css";
import "./addStock.css";

/*
 * Inventory -> Costs. Products whose purchase cost is still the automatic
 * estimate (78% of the selling price) or missing, and spare parts with no
 * cost -- the things that keep Profit & Loss from being real. Fix them one
 * by one, or download the list, fill in the cost column and upload it.
 * API: GET /costs/review/, POST /costs/variant/<id>/, /costs/part/<id>/, /costs/bulk/
 * (catalog.cost_views). A correction applies to future sales; bills already
 * raised keep the cost they were sold at.
 */

const digits = (v) => v.replace(/\D/g, "").slice(0, 9);

function message(err, fallback) {
  const b = err?.body;
  return b?.detail || b?.cost?.[0] || b?.cost || b?.rows || err?.message || fallback;
}

function CostRow({ row, kind, onSaved }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    if (!(Number(value) > 0)) { setError("Enter the cost (₹1 or more)."); return; }
    setBusy(true);
    setError("");
    try {
      await api.post(`/costs/${kind}/${row.id}/`, { cost: Number(value) });
      onSaved(row, Number(value));
    } catch (err) {
      setError(message(err, "The cost couldn't be saved."));
    } finally {
      setBusy(false);
    }
  };
  const margin = Number(value) > 0 && row.sell_price ? row.sell_price - Number(value) : null;
  return (
    <li className="cr-row">
      <div className="min-w-0">
        <p className="cr-title">{kind === "variant" ? row.product : row.name}</p>
        <p className="cr-sub as-mono">{row.code}{kind === "variant" && row.spec ? ` · ${row.spec}${row.colour ? ` / ${row.colour}` : ""}` : ""}</p>
        <p className="cr-sub">
          {kind === "variant" && <>Sells at <b className="as-mono">{money(row.sell_price)}</b> · </>}
          {row.cost ? <>using estimate <b className="as-mono">{money(row.cost)}</b> · </> : <span className="st-badge" data-tone="red">no cost</span>}{" "}
          {row.in_stock} in stock{kind === "variant" && row.sold_90d ? ` · ${row.sold_90d} sold in 90 days` : ""}
        </p>
        {error && <p className="st-err">{error}</p>}
      </div>
      <div className="cr-edit">
        <input className="st-input as-mono" inputMode="numeric" value={value} placeholder="Real cost ₹" aria-label={`Real cost of ${row.code}`}
          onChange={(e) => { setValue(digits(e.target.value)); setError(""); }} onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        <button type="button" className="st-btn" data-variant="primary" onClick={save} disabled={busy || !value}>{busy ? "Saving…" : "Save"}</button>
        {margin !== null && <span className="cr-sub as-mono" style={margin < 0 ? { color: "var(--cb-red)" } : undefined}>margin {money(margin)}</span>}
      </div>
    </li>
  );
}

function BulkUpload({ review, onDone }) {
  const [parsed, setParsed] = useState(null);
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState([]);
  const fileRef = useRef(null);

  const download = () => {
    const url = URL.createObjectURL(new Blob(["﻿" + toSheet(review)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `costs-to-fill-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const read = async (file) => {
    setProblems([]);
    setFileName(file?.name || "");
    if (!file) { setParsed(null); return; }
    if (file.size > 2_000_000) { setParsed({ rows: [], skipped: 0, problems: ["That file is too large -- keep it under 2 MB."] }); return; }
    setParsed(fromSheet(await file.text()));
  };

  const save = async () => {
    setBusy(true);
    setProblems([]);
    try {
      const result = await api.post("/costs/bulk/", { rows: parsed.rows });
      setParsed(null);
      setFileName("");
      if (fileRef.current) fileRef.current.value = "";
      onDone(result.saved);
    } catch (err) {
      setProblems(err?.body?.problems?.length ? err.body.problems : [message(err, "The costs couldn't be saved.")]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="cr-bulk" aria-labelledby="cr-bulk-title">
      <h3 id="cr-bulk-title" className="as-section-title">Many at once</h3>
      <p className="st-help">Download the list, type each real cost in the <b>cost</b> column (Excel or Google Sheets, saved as CSV), then upload it.
        Rows left empty are skipped. Nothing is saved unless every filled row is valid.</p>
      <div className="cr-bulk-actions">
        <button type="button" className="st-btn" onClick={download} disabled={!review.variants.length && !review.parts.length}><Download size={14} aria-hidden="true" /> Download list (CSV)</button>
        <label className="st-btn" style={{ cursor: "pointer" }}>
          <Upload size={14} aria-hidden="true" /> {fileName || "Upload filled sheet"}
          <input ref={fileRef} type="file" accept=".csv,.txt,text/csv,text/plain" className="sr-only" onChange={(e) => read(e.target.files?.[0])} />
        </label>
      </div>
      {parsed && (
        <div className="mt-2 space-y-2">
          {parsed.problems.length > 0 && <Alert>{parsed.problems.join(" ")}</Alert>}
          {parsed.problems.length === 0 && (
            <p className="st-help">{parsed.rows.length} {parsed.rows.length === 1 ? "cost" : "costs"} ready{parsed.skipped ? ` · ${parsed.skipped} left empty (skipped)` : ""}.</p>
          )}
          {parsed.problems.length === 0 && parsed.rows.length > 0 && (
            <button type="button" className="st-btn" data-variant="primary" onClick={save} disabled={busy}>{busy ? "Saving…" : `Save ${parsed.rows.length} ${parsed.rows.length === 1 ? "cost" : "costs"}`}</button>
          )}
        </div>
      )}
      {problems.length > 0 && <div className="mt-2"><Alert>{problems.join(" ")}</Alert></div>}
    </section>
  );
}

export default function CostReviewModal({ onClose, onChanged }) {
  const [review, setReview] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("variants");
  const [flash, setFlash] = useState("");

  const load = useCallback(() => {
    api.get("/costs/review/").then(setReview, (err) => setError(message(err, "The list couldn't be loaded.")));
  }, []);
  useEffect(() => { load(); }, [load]);

  const say = (text) => { setFlash(text); setTimeout(() => setFlash(""), 5000); };
  const onSaved = (row, cost) => {
    setReview((r) => ({
      ...r,
      [tab]: r[tab].filter((x) => x.id !== row.id),
      summary: { ...r.summary, [tab === "variants" ? "variants_to_fix" : "parts_to_fix"]: r.summary[tab === "variants" ? "variants_to_fix" : "parts_to_fix"] - 1 },
    }));
    say(`Saved ${row.code} at ${money(cost)}. Sales from now on use it.`);
    onChanged?.();
  };
  const onBulk = (saved) => {
    say(`Saved ${saved} ${saved === 1 ? "cost" : "costs"}. Sales from now on use them.`);
    load();
    onChanged?.();
  };

  const rows = review ? review[tab] : [];
  return (
    <Dialog size="wide" onClose={onClose} title="Purchase costs"
      subtitle="Profit is only real when each product's purchase cost is. These still use an estimate (78% of the selling price) or have no cost at all. Best-selling first. A correction applies to sales from now on — bills already raised keep the cost they were sold at."
      footer={<button type="button" className="st-btn" onClick={onClose}>Close</button>}>
      {error && <Alert>{error}</Alert>}
      {!review && !error && <p className="st-help">Loading…</p>}
      {review && (
        <div className="st cr-body">
          {flash && <Alert tone="ok">{flash}</Alert>}
          <div className="cr-summary">
            <span className="st-badge" data-tone={review.summary.variants_to_fix ? "amber" : "green"}>
              {review.summary.variants_to_fix ? `${review.summary.variants_to_fix} of ${review.summary.variants_total} products need a real cost` : "Every product has a real cost"}
            </span>
            <span className="st-badge" data-tone={review.summary.parts_to_fix ? "amber" : "green"}>
              {review.summary.parts_to_fix ? `${review.summary.parts_to_fix} spare parts have no cost` : "Every spare part has a cost"}
            </span>
          </div>
          <div className="as-choice cr" role="radiogroup" aria-label="Which list">
            <button type="button" role="radio" aria-checked={tab === "variants"} onClick={() => setTab("variants")}>Products ({review.variants.length})</button>
            <button type="button" role="radio" aria-checked={tab === "parts"} onClick={() => setTab("parts")}>Spare parts ({review.parts.length})</button>
          </div>
          {rows.length ? (
            <ul className="cr-list">{rows.map((row) => <CostRow key={row.id} row={row} kind={tab === "variants" ? "variant" : "part"} onSaved={onSaved} />)}</ul>
          ) : (
            <p className="st-help">Nothing to fix here.</p>
          )}
          <BulkUpload review={review} onDone={onBulk} />
        </div>
      )}
    </Dialog>
  );
}
