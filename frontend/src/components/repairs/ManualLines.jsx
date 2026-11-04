import { Plus, Trash2 } from "lucide-react";

import { blankLine, linesTotal } from "./bookingModel";
import { C, F, money } from "../../lib/theme";

// work | qty | price | our cost | remove
export const LINE_GRID = { display: "grid", gridTemplateColumns: "minmax(0,1fr) 3.25rem 5.25rem 5.25rem 1.5rem", gap: "0.375rem" };

export function LineHeader({ small = false }) {
  const style = { fontFamily: F.body, color: C.inkSoft, fontSize: small ? 10 : 11 };
  return (
    <div style={LINE_GRID} className="uppercase" aria-hidden="true">
      <span style={style}>Work / part</span><span style={style}>Qty</span><span style={style}>Price</span>
      <span style={style} title="What the parts on this line cost the shop. Never shown to the customer -- used only for the profit report. Leave blank for labour.">Our cost</span><span />
    </div>
  );
}

// Work / parts and their agreed prices, typed in at the counter (bargaining happens, so nothing is pre-priced).
// "Our cost" is optional and staff-only: what the parts cost us, so repair profit is real.
export default function ManualLines({ lines, onChange }) {
  const update = (i, patch) => onChange(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  return (
    <div className="space-y-1.5">
      <LineHeader />
      {lines.map((l, i) => (
        <div key={i} style={LINE_GRID}>
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" value={l.description} onChange={(e) => update(i, { description: e.target.value })} placeholder="Work / part, e.g. Motherboard repair" style={{ border: `1px solid ${C.rule}` }} aria-label="Work or part" />
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="1" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} style={{ border: `1px solid ${C.rule}` }} aria-label="Quantity" />
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} placeholder="₹ price" style={{ border: `1px solid ${C.rule}` }} aria-label="Price" />
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_cost ?? ""} onChange={(e) => update(i, { unit_cost: e.target.value })} placeholder="₹ cost" style={{ border: `1px dashed ${C.rule}` }} aria-label="Our cost (staff only)" />
          <button type="button" onClick={() => onChange(lines.length > 1 ? lines.filter((_, n) => n !== i) : [blankLine()])} className="flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => onChange([...lines, blankLine()])} className="flex items-center gap-1 text-xs" style={{ color: C.blue }}><Plus size={13} /> Add line</button>
        <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>Total {money(linesTotal(lines))}</span>
      </div>
    </div>
  );
}
