import { Plus, Trash2 } from "lucide-react";

import { blankLine, linesTotal } from "./bookingModel";
import { C, F, money } from "../../lib/theme";

// Work / parts and their agreed prices, typed in at the counter (bargaining happens, so nothing is pre-priced).
export default function ManualLines({ lines, onChange }) {
  const update = (i, patch) => onChange(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  return (
    <div className="space-y-1.5">
      {lines.map((l, i) => (
        <div key={i} className="grid grid-cols-12 gap-1.5">
          <input className="col-span-6 bg-transparent px-2 py-1.5 text-sm" value={l.description} onChange={(e) => update(i, { description: e.target.value })} placeholder="Work / part, e.g. Motherboard repair" style={{ border: `1px solid ${C.rule}` }} aria-label="Work or part" />
          <input className="col-span-2 bg-transparent px-2 py-1.5 text-sm" type="number" min="1" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} style={{ border: `1px solid ${C.rule}` }} aria-label="Quantity" />
          <input className="col-span-3 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} placeholder="₹ price" style={{ border: `1px solid ${C.rule}` }} aria-label="Price" />
          <button type="button" onClick={() => onChange(lines.length > 1 ? lines.filter((_, n) => n !== i) : [blankLine()])} className="col-span-1 flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => onChange([...lines, blankLine()])} className="flex items-center gap-1 text-xs" style={{ color: C.blue }}><Plus size={13} /> Add line</button>
        <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>Total {money(linesTotal(lines))}</span>
      </div>
    </div>
  );
}
