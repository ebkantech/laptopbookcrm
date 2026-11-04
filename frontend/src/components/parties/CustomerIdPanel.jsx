import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BadgeCheck, Eye, IdCard, Plus, Trash2, X } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, fmt } from "../../lib/theme";
import { ErrorNote, Pill } from "../Atoms";
import { ID_TYPES, KYC_LABEL, idProblem } from "./customerIds";

const STATUS_COLOR = { verified: C.green, format_ok: C.amber, not_verified: C.amber, failed: C.carbon };
const KYC_COLOR = { verified: C.green, unverified: C.amber, none: C.carbon };

/* A customer's identity documents (parties.kyc). Aadhaar is kept masked --
 * last 4 digits only -- and every record needs the customer's consent.
 * "Verify" = a staff member checked the original document. */
export default function CustomerIdPanel({ partyId, canManage, canDelete = false, onStatus }) {
  const [data, setData] = useState(null);
  const [adding, setAdding] = useState(false);
  const [verifying, setVerifying] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!partyId) return;
    api.get(`/party-ids/?party=${partyId}`).then((d) => { setData(d); onStatus?.(d.status); }).catch((e) => setError(e.message));
  }, [partyId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setData(null); load(); }, [load]);

  if (!partyId) return null;
  const view = async (doc) => {
    try { window.open(await api.blobUrl(`/party-ids/${doc.id}/file/`), "_blank", "noopener"); } catch (e) { setError(e.message); }
  };
  const remove = async (doc) => {
    if (!window.confirm(`Delete this ${doc.id_type_label} record${doc.has_file ? " and its copy" : ""}?`)) return;
    try { await api.del(`/party-ids/${doc.id}/`); load(); } catch (e) { setError(e.message); }
  };
  const status = data?.status;
  return (
    <section className="mt-3 rounded-lg p-3" aria-label="Customer ID" style={{ backgroundColor: C.slip2, border: `1px solid ${status === "verified" ? C.rule : C.amber}` }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>
          <IdCard size={14} style={{ color: C.stamp }} />Customer ID
          {status && <Pill color={KYC_COLOR[status]}>{KYC_LABEL[status]}</Pill>}
        </p>
        {canManage && !adding && <button type="button" onClick={() => setAdding(true)} className="flex items-center gap-1 px-2 py-1 text-[11px]" style={{ border: `1px solid ${C.rule}`, fontWeight: 600, color: C.ink }}><Plus size={11} />Add ID</button>}
      </div>
      {status && status !== "verified" && (
        <p className="mt-1 flex items-start gap-1 text-[11px]" style={{ color: C.amber }}>
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {status === "none" ? "No ID recorded for this customer yet." : "ID recorded but not checked against the original yet."} The agreement can still go ahead.
        </p>
      )}
      <ErrorNote message={error} />
      {(data?.documents || []).map((d) => (
        <div key={d.id} className="mt-2 rounded px-2.5 py-2 text-xs" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <span className="min-w-0">
              <b>{d.id_type_label}</b> <span style={{ fontFamily: F.mono }}>{d.number}</span>{d.name_on_id && <span style={{ color: C.inkSoft }}> · {d.name_on_id}</span>}
              <span className="block" style={{ color: C.inkSoft }}>{d.check_note}</span>
              {d.verified_at && <span className="block" style={{ color: d.status === "failed" ? C.carbon : C.inkSoft }}>{d.status === "failed" ? "Failed" : "Verified"} by {d.verified_by} · {fmt(d.verified_at)}{d.verify_note && ` — ${d.verify_note}`}</span>}
              <span className="block" style={{ color: C.inkSoft }}>Consent taken by {d.consent_by} · {fmt(d.consent_at)}</span>
            </span>
            <Pill color={STATUS_COLOR[d.status]}>{d.status_label}</Pill>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {canManage && d.has_file && <button type="button" onClick={() => view(d)} className="flex items-center gap-1 px-1.5 py-0.5 text-[11px]" style={{ border: `1px solid ${C.rule}` }}><Eye size={11} />View copy</button>}
            {canManage && d.status !== "verified" && <button type="button" onClick={() => setVerifying(d)} className="flex items-center gap-1 px-1.5 py-0.5 text-[11px]" style={{ border: `1px solid ${C.green}`, color: C.green, fontWeight: 600 }}><BadgeCheck size={11} />Verify</button>}
            {canDelete && <button type="button" onClick={() => remove(d)} className="flex items-center gap-1 px-1.5 py-0.5 text-[11px]" style={{ border: `1px solid ${C.rule}`, color: C.carbon }}><Trash2 size={11} />Delete</button>}
          </div>
        </div>
      ))}
      {adding && <AddIdForm partyId={partyId} onCancel={() => setAdding(false)} onSaved={(warning) => { setAdding(false); if (warning) setError(warning); load(); }} />}
      {verifying && <VerifyForm doc={verifying} onCancel={() => setVerifying(null)} onSaved={() => { setVerifying(null); load(); }} />}
    </section>
  );
}

const field = { border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body };

function AddIdForm({ partyId, onCancel, onSaved }) {
  const [type, setType] = useState("aadhaar");
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [masked, setMasked] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const hint = ID_TYPES.find((t) => t.id === type)?.hint;

  const save = async () => {
    const problem = idProblem(type, number);
    if (problem) return setError(problem);
    if (!consent) return setError("Tick the consent box — the customer must agree to their ID being recorded.");
    if (file && type === "aadhaar" && !masked) return setError("Only a masked Aadhaar copy may be kept — confirm the first 8 digits are hidden on it.");
    const fd = new FormData();
    fd.append("party", partyId); fd.append("id_type", type); fd.append("number", number.trim());
    fd.append("name_on_id", name.trim()); fd.append("consent", "true");
    if (file) { fd.append("file", file); fd.append("masked_copy", masked ? "true" : "false"); }
    setBusy(true); setError("");
    try { const r = await api.upload("/party-ids/", fd); onSaved(r.warning); }
    catch (e) { setError(e.body?.number || e.body?.file || e.body?.consent || e.message); setBusy(false); }
  };
  return (
    <div className="mt-2 rounded p-2.5" style={{ border: `1px solid ${C.stamp}`, backgroundColor: C.slip }}>
      <div className="flex items-center justify-between"><span className="text-[11px] uppercase" style={{ fontWeight: 700, letterSpacing: "0.1em", color: C.inkSoft }}>Add an ID</span><button type="button" onClick={onCancel} aria-label="Cancel"><X size={14} style={{ color: C.inkSoft }} /></button></div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="text-[11px]" style={{ color: C.inkSoft }}>ID type
          <select value={type} onChange={(e) => { setType(e.target.value); setError(""); }} className="mt-1 w-full bg-transparent p-1.5 text-sm" style={field}>
            {ID_TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
        <label className="text-[11px]" style={{ color: C.inkSoft }}>Number {hint && <span>({hint})</span>}
          <input value={number} onChange={(e) => { setNumber(e.target.value); setError(""); }} autoComplete="off" className="mt-1 w-full bg-transparent p-1.5 text-sm" style={{ ...field, fontFamily: F.mono }} />
        </label>
        <label className="text-[11px] sm:col-span-2" style={{ color: C.inkSoft }}>Name as printed on the ID (optional)
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className="mt-1 w-full bg-transparent p-1.5 text-sm" style={field} />
        </label>
        <label className="text-[11px] sm:col-span-2" style={{ color: C.inkSoft }}>Copy of the ID (optional — JPG, PNG or PDF)
          <input type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} className="mt-1 block w-full text-xs" />
        </label>
      </div>
      {type === "aadhaar" && (
        <p className="mt-2 text-[11px]" style={{ color: C.inkSoft }}>Only the last 4 digits of the Aadhaar number are saved. If you attach a copy, it must be the <b>masked Aadhaar</b> (first 8 digits hidden).</p>
      )}
      {type === "aadhaar" && file && (
        <label className="mt-1 flex items-start gap-2 text-[11px]" style={{ color: C.ink }}><input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)} className="mt-0.5" />The attached copy is a masked Aadhaar — the first 8 digits are hidden.</label>
      )}
      <label className="mt-2 flex items-start gap-2 text-[11px]" style={{ color: C.ink }}>
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
        The customer has agreed to their ID being recorded for this rental. (Your name and the time are saved with it.)
      </label>
      <ErrorNote message={error} />
      <button type="button" onClick={save} disabled={busy} className="mt-2 px-3 py-1.5 text-xs" style={{ backgroundColor: C.stamp, color: C.onAccent, fontWeight: 700, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Save ID"}</button>
    </div>
  );
}

function VerifyForm({ doc, onCancel, onSaved }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const send = async (outcome) => {
    if (outcome === "failed" && !note.trim()) return setError("Say what was wrong with the ID.");
    try { await api.post(`/party-ids/${doc.id}/verify/`, { outcome, note: note.trim() }); onSaved(); }
    catch (e) { setError(e.message); }
  };
  return (
    <div className="mt-2 rounded p-2.5" style={{ border: `1px solid ${C.green}`, backgroundColor: C.slip }}>
      <p className="text-xs" style={{ color: C.ink }}>Check the customer's <b>original</b> {doc.id_type_label} — photo, name and number ({doc.number}) — then record the result.</p>
      <input value={note} maxLength={200} onChange={(e) => { setNote(e.target.value); setError(""); }} placeholder="Note (required if it fails), e.g. original card seen at counter" className="mt-2 w-full bg-transparent p-1.5 text-sm" style={field} />
      <ErrorNote message={error} />
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => send("verified")} className="px-3 py-1.5 text-xs" style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 700 }}>Original checked — verified</button>
        <button type="button" onClick={() => send("failed")} className="px-3 py-1.5 text-xs" style={{ border: `1px solid ${C.carbon}`, color: C.carbon, fontWeight: 700 }}>Doesn't match — failed</button>
        <button type="button" onClick={onCancel} className="text-xs underline" style={{ color: C.inkSoft }}>Cancel</button>
      </div>
    </div>
  );
}
