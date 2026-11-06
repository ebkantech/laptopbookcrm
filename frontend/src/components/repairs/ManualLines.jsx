import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";

import { blankLine, linesTotal } from "./bookingModel";
import { api } from "../../lib/api";
import { C, F, money } from "../../lib/theme";

// work | qty | price | our cost | remove
export const LINE_GRID = { display: "grid", gridTemplateColumns: "minmax(0,1fr) 3.25rem 5.25rem 5.25rem 1.5rem", gap: "0.375rem" };
// the same grid without the "our cost" column (New Repair Ticket form)
export const LINE_GRID_NO_COST = { ...LINE_GRID, gridTemplateColumns: "minmax(0,1fr) 3.25rem 5.25rem 1.5rem" };

export function LineHeader({ small = false, showCost = true }) {
  const style = { fontFamily: F.body, color: C.inkSoft, fontSize: small ? 10 : 11 };
  return (
    <div style={showCost ? LINE_GRID : LINE_GRID_NO_COST} className="uppercase" aria-hidden="true">
      <span style={style}>Work / part</span><span style={style}>Qty</span><span style={style}>Price</span>
      {showCost && <span style={style} title="What the parts on this line cost the shop. Never shown to the customer -- used only for the profit report. Leave blank for labour.">Our cost</span>}<span />
    </div>
  );
}

const fieldStyle = { border: `1px solid ${C.rule}` };

// The Work / part (product name) box of a New Repair Ticket line: type to search the shop's
// inventory parts (non-laptop, serial-tracked, in stock there). Picking one links the line to
// that product; its serial number is typed in the separate Serial Number field below.
// Text that isn't picked stays a plain work/labour line with no stock effect.
function PartSearchInput({ line, onChange, stockPointId }) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState(null);
  const [failed, setFailed] = useState("");
  const seq = useRef(0);
  const box = useRef(null);
  const linked = !!line.variant;

  useEffect(() => {
    if (!open || linked || !stockPointId) return undefined;
    const mine = ++seq.current;
    const t = setTimeout(() => {
      api.get(`/repair-parts/?stock_point=${stockPointId}&q=${encodeURIComponent((line.description || "").trim())}`)
        .then((rows) => { if (mine === seq.current) { setResults(rows); setFailed(""); } })
        .catch((e) => { if (mine === seq.current) { setResults([]); setFailed(e.message); } });
    }, 250);
    return () => clearTimeout(t);
  }, [open, linked, stockPointId, line.description]);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  // A part, or a catalogue repair service (which may fit an inventory part -- then its serial is asked for too).
  const pick = (row) => {
    const service = row.kind === "service";
    onChange({
      description: row.label, service_id: service ? row.service : null, variant: row.variant || null, available: row.available,
      serial_number: "", serial_check: null,
      ...(row.variant ? { quantity: 1 } : {}),
      ...(service && String(line.unit_price ?? "") === "" ? { unit_price: String(row.charge) } : {}),
    });
    setOpen(false);
  };
  const unlink = () => onChange({ description: "", service_id: null, variant: null, available: null, serial_number: "", serial_check: null });
  const services = (results || []).filter((r) => r.kind === "service");
  const parts = (results || []).filter((r) => r.kind !== "service");
  const group = (title) => <p className="px-3 pb-1 pt-2 text-[10px] uppercase" style={{ color: C.inkSoft, fontFamily: F.body, letterSpacing: "0.08em" }}>{title}</p>;

  return (
    <div ref={box} className="relative min-w-0">
      <input className={`w-full min-w-0 bg-transparent py-1.5 pl-2 text-sm ${linked ? "pr-7" : "pr-2"}`} value={line.description} readOnly={linked} title={linked ? line.description : undefined}
        onChange={(e) => onChange({ description: e.target.value })}
        onFocus={() => setOpen(true)} onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        placeholder="Product / work name" style={fieldStyle} aria-label="Work or part"
        role="combobox" aria-expanded={open && !linked} aria-autocomplete="list" autoComplete="off" />
      {linked && (
        <button type="button" onClick={unlink} aria-label="Change part" title="Choose a different part"
          className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full hover:bg-black/5"><X size={13} style={{ color: C.inkSoft }} /></button>
      )}
      {open && !linked && (
        <div role="listbox" aria-label="Repair services and parts in stock at this shop" className="absolute left-0 right-0 z-20 mt-1 max-h-56 overflow-y-auto"
          style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 8px 24px rgba(0,0,0,0.18)" }}>
          {results === null && <p className="px-3 py-2 text-xs" style={{ color: C.inkSoft }}>Searching inventory…</p>}
          {failed && <p className="px-3 py-2 text-xs" style={{ color: C.carbon }}>{failed}</p>}
          {results && !failed && !results.length && (
            <p className="px-3 py-2 text-xs" style={{ color: C.inkSoft }}>
              {(line.description || "").trim() ? "No matching repair service or part in stock at this shop. Keep typing to add it as plain work." : "No repair services or parts in stock at this shop."}
            </p>
          )}
          {services.length > 0 && group("Repair services")}
          {services.map((r) => (
            <button key={`s${r.service}`} type="button" role="option" aria-selected="false" onClick={() => pick(r)}
              className="flex w-full items-start justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-black/5" style={{ color: C.ink, fontFamily: F.body }}>
              <span className="min-w-0 break-words">{r.label}{r.variant ? <span className="block text-xs" style={{ color: C.inkSoft }}>Fits {r.part_label}</span> : null}</span>
              <span className="shrink-0 text-xs" style={{ color: r.variant && !r.available ? C.carbon : C.inkSoft, fontFamily: F.mono }}>{r.variant ? `${r.available} in stock` : "labour"}</span>
            </button>
          ))}
          {parts.length > 0 && group("Inventory parts")}
          {parts.map((r) => (
            <button key={`p${r.variant}`} type="button" role="option" aria-selected="false" onClick={() => pick(r)}
              className="flex w-full items-start justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-black/5" style={{ color: C.ink, fontFamily: F.body }}>
              <span className="min-w-0 break-words">{r.label}</span>
              <span className="shrink-0 text-xs" style={{ color: C.inkSoft, fontFamily: F.mono }}>{r.available} in stock</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// The separate Serial Number field of a line linked to an inventory product: required, typed in
// from the unit, and checked against the inventory records (this product, in stock at this shop).
// The server checks it again, under a lock, when the ticket is booked.
function SerialNumberField({ line, onChange, stockPointId, takenElsewhere }) {
  const seq = useRef(0);
  // the answer arrives later: report it through the newest onChange, so it lands on the newest lines
  const latest = useRef(onChange);
  latest.current = onChange;
  const typed = (line.serial_number || "").trim();

  useEffect(() => {
    if (!typed) return undefined;
    if (takenElsewhere) {
      onChange({ serial_check: { state: "bad", message: `Serial ${typed} is already entered on another line.` } });
      return undefined;
    }
    const mine = ++seq.current;
    onChange({ serial_check: { state: "checking", message: "Checking serial number…" } });
    const t = setTimeout(() => {
      api.get(`/repair-parts/check-serial/?stock_point=${stockPointId}&variant=${line.variant}&serial=${encodeURIComponent(typed)}`)
        .then((r) => { if (mine === seq.current) latest.current({ serial_check: { state: r.ok ? "ok" : "bad", message: r.message } }); })
        .catch((e) => { if (mine === seq.current) latest.current({ serial_check: { state: "bad", message: e.message || "Couldn't check the serial number." } }); });
    }, 400);
    return () => clearTimeout(t);
    // onChange is a fresh closure every render; the check depends only on what was typed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed, line.variant, stockPointId, takenElsewhere]);

  const check = typed ? line.serial_check : null;
  const bad = !typed || check?.state === "bad";
  return (
    <input value={line.serial_number || ""} onChange={(e) => onChange({ serial_number: e.target.value, serial_check: null })}
      placeholder="Enter inventory serial" autoComplete="off" spellCheck="false" aria-required="true" aria-invalid={bad}
      aria-label="Inventory part serial number (mandatory)"
      className="w-full min-w-0 bg-transparent px-2 py-1.5 text-sm outline-none"
      style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${bad ? C.carbon : C.rule}` }} />
  );
}

// The message under a linked line's serial: what's missing, or what the inventory check said.
function serialMessage(line) {
  const typed = (line.serial_number || "").trim();
  if (!typed) {
    return { color: C.carbon, text: line.available ? "Serial Number is mandatory for this inventory part: type the serial on the part being fitted." : "No unit of this part is available at this shop. Choose another part." };
  }
  const check = line.serial_check;
  if (!check) return null;
  return { color: check.state === "ok" ? C.green : check.state === "bad" ? C.carbon : C.inkSoft, text: check.message, alert: check.state === "bad" };
}

// New Repair Ticket row: work / part | serial number (mandatory) | qty | price | remove.
// Below the sm breakpoint the serial cell drops to its own full-width line under the row.
const ROW_WITH_SERIAL = "grid gap-1.5 grid-cols-[minmax(0,1fr)_3.25rem_5.25rem_1.5rem] sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_3.25rem_5.25rem_1.5rem]";

// Work / parts and their agreed prices, typed in at the counter (bargaining happens, so nothing is pre-priced).
// "Our cost" is optional and staff-only: what the parts cost us, so repair profit is real.
// With `stockPointId` (New Repair Ticket) the Work / part box also searches that shop's inventory parts.
export default function ManualLines({ lines, onChange, showCost = true, stockPointId = null }) {
  const update = (i, patch) => onChange(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  const remove = (i) => onChange(lines.length > 1 ? lines.filter((_, n) => n !== i) : [blankLine()]);
  const footer = (
    <div className="flex items-center justify-between">
      <button type="button" onClick={() => onChange([...lines, blankLine()])} className="flex items-center gap-1 text-xs" style={{ color: C.blue }}><Plus size={13} /> Add line</button>
      <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>Total {money(linesTotal(lines))}</span>
    </div>
  );

  if (stockPointId) {
    const head = { fontFamily: F.body, color: C.inkSoft, fontSize: 11 };
    return (
      <div className="space-y-1.5">
        <div className={`${ROW_WITH_SERIAL} uppercase`} aria-hidden="true">
          <span style={head}>Work / part</span>
          <span style={head} className="hidden sm:block" title="Serial number of the inventory part fitted. Mandatory when the line is a part picked from Inventory; not needed for labour.">Serial number (mandatory)</span>
          <span style={head}>Qty</span><span style={head}>Price</span><span />
        </div>
        {lines.map((l, i) => {
          const taken = new Set(lines.filter((o, n) => n !== i && o.variant).map((o) => (o.serial_number || "").trim().toUpperCase()).filter(Boolean));
          const msg = l.variant ? serialMessage(l) : null;
          return (
            <div key={i} className="space-y-1">
              <div className={ROW_WITH_SERIAL}>
                <PartSearchInput line={l} onChange={(patch) => update(i, patch)} stockPointId={stockPointId} />
                <div className="order-last col-span-full sm:order-none sm:col-span-1">
                  {l.variant
                    ? <SerialNumberField line={l} onChange={(patch) => update(i, patch)} stockPointId={stockPointId}
                        takenElsewhere={!!(l.serial_number || "").trim() && taken.has((l.serial_number || "").trim().toUpperCase())} />
                    : <input disabled value="" placeholder="Not needed" aria-label="Serial number (only for inventory parts)"
                        className="hidden w-full min-w-0 bg-transparent px-2 py-1.5 text-sm sm:block" style={{ border: `1px dashed ${C.rule}`, opacity: 0.55 }} />}
                </div>
                <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="1" value={l.variant ? 1 : l.quantity} readOnly={!!l.variant} title={l.variant ? "One serial-numbered unit per line -- add another line for a second unit" : undefined} onChange={(e) => update(i, { quantity: e.target.value })} style={fieldStyle} aria-label="Quantity" />
                <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} placeholder="₹ price" style={fieldStyle} aria-label="Price" />
                <button type="button" onClick={() => remove(i)} className="flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button>
              </div>
              {msg && <p role={msg.alert ? "alert" : undefined} className="break-words text-xs" style={{ fontFamily: F.body, color: msg.color }}>{msg.text}</p>}
            </div>
          );
        })}
        {footer}
      </div>
    );
  }

  const grid = showCost ? LINE_GRID : LINE_GRID_NO_COST;
  return (
    <div className="space-y-1.5">
      <LineHeader showCost={showCost} />
      {lines.map((l, i) => (
        <div key={i} style={grid}>
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" value={l.description} onChange={(e) => update(i, { description: e.target.value })} placeholder="Work / part, e.g. Motherboard repair" style={fieldStyle} aria-label="Work or part" />
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="1" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} style={fieldStyle} aria-label="Quantity" />
          <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} placeholder="₹ price" style={fieldStyle} aria-label="Price" />
          {showCost && <input className="min-w-0 bg-transparent px-2 py-1.5 text-sm" type="number" min="0" value={l.unit_cost ?? ""} onChange={(e) => update(i, { unit_cost: e.target.value })} placeholder="₹ cost" style={{ border: `1px dashed ${C.rule}` }} aria-label="Our cost (staff only)" />}
          <button type="button" onClick={() => remove(i)} className="flex items-center justify-center" aria-label="Remove line"><Trash2 size={14} style={{ color: C.carbon }} /></button>
        </div>
      ))}
      {footer}
    </div>
  );
}
