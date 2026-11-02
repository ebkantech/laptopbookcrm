import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, money } from "../../lib/theme";
import { ErrorNote } from "../Atoms";
import { LINE_KINDS, billPayload, billTotal, lineAmount, validateBill, validateLine } from "./leadModel";
import { Modal, inputStyle } from "./Prompt";

const blank = (kind = "labour") => ({ key: Math.random().toString(36).slice(2), kind, description: "", qty: 1, price: "", part: "", variant: "" });

/* Prepare (or revise) the bill. The visit charge is added by the server as
 * the first line; parts and products are picked from stock so the work can
 * deduct them later. */
export default function BillEditor({ lead, onClose, onSaved }) {
  const [lines, setLines] = useState(() => {
    const existing = (lead.quote?.lines || []).filter((l) => l.kind !== "visit");
    return existing.length ? existing.map((l) => ({ ...l, key: String(l.id), part: l.part || "", variant: l.variant || "" })) : [blank()];
  });
  const [note, setNote] = useState(lead.quote?.note || "");
  const [parts, setParts] = useState([]);
  const [variants, setVariants] = useState([]);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getAll("/parts/").then(setParts).catch(() => {});
    api.getAll("/products/").then((all) => setVariants(all.flatMap((p) => p.variants.map((v) => ({ id: v.id, label: `${p.display_name} · ${v.spec}${v.colour ? `, ${v.colour}` : ""}`, price: v.sell_price, stock: v.stock })))))
      .catch(() => {});
  }, []);

  const partQty = (p) => (p.stock || []).reduce((n, s) => n + (s.quantity || 0), 0);
  const update = (key, patch) => setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const total = billTotal(lines, lead.visit_charge);

  const save = async () => {
    setChecked(true);
    const problem = validateBill(lines);
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError("");
    try {
      onSaved(await api.post(`/leads/${lead.id}/quote/`, billPayload(lines, note)));
    } catch (e) {
      setError(e.body?.lines ? [].concat(e.body.lines).join(" ") : e.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={`Bill for ${lead.code}`} onClose={onClose} wide>
      <p className="mb-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        {lead.quote ? `Saving creates version ${lead.quote.version + 1}; the client must approve it again.` : "Add the work and parts. The client approves this before any work starts."}
      </p>
      {lead.visit_charge > 0 && <div className="mb-2 flex justify-between px-3 py-2 text-sm" style={{ backgroundColor: C.slip2 }}><span>Visit charge</span><strong style={{ fontFamily: F.mono }}>{money(lead.visit_charge)}</strong></div>}
      <div className="space-y-2">
        {lines.map((l, i) => {
          const bad = checked ? validateLine(l) : "";
          return (
            <div key={l.key} className="grid gap-2 p-2 sm:grid-cols-[130px_1fr_70px_100px_auto]" style={{ border: `1px solid ${bad ? C.carbon : C.rule}` }}>
              <select aria-label={`Line ${i + 1} type`} value={l.kind} onChange={(e) => update(l.key, { kind: e.target.value, part: "", variant: "" })} className="bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>
                {LINE_KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
              {l.kind === "part" ? (
                <select aria-label={`Line ${i + 1} part`} value={l.part} onChange={(e) => { const p = parts.find((x) => String(x.id) === e.target.value); update(l.key, { part: p ? p.id : "", description: p ? p.name : "" }); }} className="min-w-0 bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>
                  <option value="">Select spare part…</option>
                  {parts.map((p) => <option key={p.id} value={p.id}>{p.name} ({partQty(p)} in stock)</option>)}
                </select>
              ) : l.kind === "product" ? (
                <select aria-label={`Line ${i + 1} product`} value={l.variant} onChange={(e) => { const v = variants.find((x) => String(x.id) === e.target.value); update(l.key, v ? { variant: v.id, description: v.label, price: l.price === "" ? v.price : l.price } : { variant: "", description: "" }); }} className="min-w-0 bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>
                  <option value="">Select product…</option>
                  {variants.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
              ) : (
                <input aria-label={`Line ${i + 1} description`} value={l.description} onChange={(e) => update(l.key, { description: e.target.value })} maxLength={160} placeholder="e.g. Replace DC jack" className="min-w-0 bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
              )}
              <div className="grid grid-cols-2 gap-2 sm:contents">
                <label className="block text-[11px] sm:contents" style={{ color: C.inkSoft }}><span className="sm:hidden">Qty</span>
                  <input aria-label={`Line ${i + 1} quantity`} value={l.qty} onChange={(e) => update(l.key, { qty: e.target.value })} inputMode="numeric" className="w-full bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
                </label>
                <label className="block text-[11px] sm:contents" style={{ color: C.inkSoft }}><span className="sm:hidden">Price each (₹)</span>
                  <input aria-label={`Line ${i + 1} price`} value={l.price} onChange={(e) => update(l.key, { price: e.target.value })} inputMode="numeric" placeholder="₹ each" className="w-full bg-transparent px-2 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
                </label>
              </div>
              <div className="flex items-center justify-between gap-2 sm:justify-end">
                <span className="text-xs sm:hidden" style={{ color: C.inkSoft }}>Amount</span>
                <span className="text-sm" style={{ fontFamily: F.mono }}>{money(lineAmount(l))}</span>
                <button type="button" aria-label={`Remove line ${i + 1}`} onClick={() => setLines((all) => (all.length > 1 ? all.filter((x) => x.key !== l.key) : all))} className="p-2" style={{ color: C.carbon }}><Trash2 size={15} /></button>
              </div>
              {bad && <p className="text-xs sm:col-span-5" style={{ color: C.carbon }}>{bad}</p>}
            </div>
          );
        })}
      </div>
      <button type="button" onClick={() => setLines((all) => [...all, blank()])} className="mt-2 flex items-center gap-1 text-xs" style={{ color: C.orange, fontWeight: 700 }}><Plus size={13} /> Add line</button>
      <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="Note for the client (optional)" aria-label="Note for the client" className="mt-3 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
      <div className="mt-3 flex justify-between px-3 py-2" style={{ border: `1px solid ${C.rule}` }}><span className="text-sm">Bill total</span><strong style={{ fontFamily: F.mono }}>{money(total)}</strong></div>
      <ErrorNote message={error} />
      <div className="mt-3 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" onClick={onClose} className="min-h-[44px] px-4 py-2 text-xs" style={{ border: `1px solid ${C.rule}` }}>Cancel</button>
        <button type="button" disabled={busy} onClick={save} className="min-h-[44px] px-5 py-2 text-xs uppercase" style={{ backgroundColor: C.orange, color: C.onAccent, fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>{busy ? "Saving…" : "Save bill"}</button>
      </div>
    </Modal>
  );
}
