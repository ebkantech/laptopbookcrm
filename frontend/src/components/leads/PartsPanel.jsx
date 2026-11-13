import { useEffect, useState } from "react";
import { PackageMinus, PackagePlus, PackageX, Undo2 } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";
import { ErrorNote, Pill } from "../Atoms";
import { Modal, inputStyle } from "./Prompt";

/* Stock handed to the technician for this job. It left the shelf when issued
 * (no invoice) and stays in their name until it is billed or handed back. */
export default function PartsPanel({ lead, onIssue, onReturn, onWriteOff }) {
  const parts = lead.parts || [];
  const acts = lead.actions || [];
  const canIssue = acts.includes("issue_parts");
  const canReturn = acts.includes("return_parts");
  const canWriteOff = acts.includes("write_off_parts");
  if (!parts.length && !canIssue) return null;
  return (
    <section className="mt-4" aria-label="Parts with the technician">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Parts with the technician</p>
        {canIssue && (
          <button type="button" onClick={onIssue} className="flex min-h-[36px] items-center gap-1.5 px-3 py-1.5 text-xs" style={{ fontWeight: 700, border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body }}>
            <PackagePlus size={14} />Issue parts
          </button>
        )}
      </div>
      {parts.length === 0 && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Nothing issued. Parts taken out for this job are recorded in the technician's name, so the stock count stays right.</p>}
      {parts.map((p) => (
        <div key={p.id} className="mt-1 px-3 py-2 text-sm" style={{ backgroundColor: p.due_now ? `color-mix(in srgb, ${C.carbon} 7%, transparent)` : C.slip2, border: p.due_now ? `1px solid ${C.carbon}` : "none" }}>
          <div className="flex items-start justify-between gap-3">
            <span className="min-w-0 break-words">{p.description}<span className="block text-xs" style={{ color: C.inkSoft }}>{p.technician_name}</span></span>
            <span className="shrink-0 text-right text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
              issued {p.qty_issued} · used {p.qty_used} · back {p.qty_returned}{p.qty_written_off > 0 && ` · lost ${p.qty_written_off}`}
              {p.outstanding > 0 && <strong className="block" style={{ color: p.due_now ? C.carbon : C.amber }}>{p.due_now ? "RETURN" : "holding"} {p.outstanding}</strong>}
            </span>
          </div>
          {p.outstanding > 0 && (canReturn || canWriteOff) && (
            <div className="mt-2 flex flex-wrap gap-2">
              {canReturn && (
                <button type="button" onClick={() => onReturn(p)} className="flex min-h-[36px] items-center gap-1.5 px-3 py-1.5 text-xs" style={{ fontWeight: 700, border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body }}>
                  <Undo2 size={13} />Take back
                </button>
              )}
              {canWriteOff && (
                <button type="button" onClick={() => onWriteOff(p)} className="flex min-h-[36px] items-center gap-1.5 px-3 py-1.5 text-xs" style={{ fontWeight: 700, border: `1px solid ${C.carbon}`, color: C.carbon, fontFamily: F.body }}>
                  <PackageX size={13} />Lost / damaged
                </button>
              )}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

export function IssuePartsModal({ lead, onClose, onSubmit }) {
  const [kind, setKind] = useState("part");
  const [parts, setParts] = useState([]);
  const [variants, setVariants] = useState([]);
  const [item, setItem] = useState("");
  const [qty, setQty] = useState("1");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getAll("/parts/").then(setParts).catch(() => {});
    api.getAll("/products/").then((all) => setVariants(all.flatMap((p) => p.variants.map((v) => ({ id: v.id, label: `${p.display_name} · ${v.spec}${v.colour ? `, ${v.colour}` : ""}` }))))).catch(() => {});
  }, []);

  const options = kind === "part" ? parts.map((p) => ({ id: p.id, label: p.name })) : variants;
  const submit = async (e) => {
    e.preventDefault();
    if (!item) { setError("Pick the item."); return; }
    if (!/^[1-9][0-9]{0,2}$/.test(qty)) { setError("Enter a quantity between 1 and 999."); return; }
    setBusy(true);
    setError("");
    try {
      await onSubmit({ kind, item: Number(item), qty: Number(qty), note: note.trim() });
    } catch (err) {
      setError(err.message || "Couldn't issue.");
      setBusy(false);
    }
  };
  const field = "mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm";
  return (
    <Modal title="Issue parts to the technician" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <p className="text-sm" style={{ color: C.inkSoft }}>Taken off {lead.stock_point_name}'s shelf now, in the name of <strong style={{ color: C.ink }}>{lead.assigned_to_name}</strong>. No invoice is raised. What the bill uses is counted as used; the rest must come back.</p>
        <div className="mt-3 flex gap-2" role="radiogroup" aria-label="Type">
          {[["part", "Spare part"], ["product", "Product"]].map(([v, l]) => (
            <button key={v} type="button" role="radio" aria-checked={kind === v} onClick={() => { setKind(v); setItem(""); }} className="min-h-[40px] px-4 text-xs"
              style={{ fontWeight: 700, fontFamily: F.body, border: `1px solid ${kind === v ? C.orange : C.rule}`, color: kind === v ? C.orange : C.ink }}>{l}</button>
          ))}
        </div>
        <label className="mt-3 block text-xs" style={{ fontWeight: 700 }}>Item
          <select value={item} onChange={(e) => { setItem(e.target.value); setError(""); }} className={field} style={inputStyle(false)}>
            <option value="">Select…</option>
            {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
        <label className="mt-3 block text-xs" style={{ fontWeight: 700 }}>Quantity
          <input value={qty} onChange={(e) => { setQty(e.target.value); setError(""); }} inputMode="numeric" className={field} style={inputStyle(false)} />
        </label>
        <label className="mt-3 block text-xs" style={{ fontWeight: 700 }}>Note (optional)
          <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} className={field} style={inputStyle(false)} />
        </label>
        <ErrorNote message={error} />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="min-h-[44px] px-4 text-xs" style={{ border: `1px solid ${C.rule}`, fontWeight: 700 }}>Cancel</button>
          <button type="submit" disabled={busy} className="flex min-h-[44px] items-center gap-1.5 px-4 text-xs disabled:opacity-50" style={{ backgroundColor: C.orange, color: C.onAccent, fontWeight: 700 }}><PackageMinus size={14} />{busy ? "Issuing…" : "Issue to technician"}</button>
        </div>
      </form>
    </Modal>
  );
}
