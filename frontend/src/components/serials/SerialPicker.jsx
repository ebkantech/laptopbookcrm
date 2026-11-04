import { useEffect, useState } from "react";
import { ScanLine } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

/* Pick which units of a serial-tracked product are going out. Tap a serial,
 * or scan its label into the box (a scanner types the code and presses Enter).
 * `need` = how many must be picked: units received before tracking may go
 * without one, so need = qty minus those. */
export default function SerialPicker({ variantId, stockPointId, qty, value, onChange, onInfo }) {
  const [info, setInfo] = useState(null);
  const [scan, setScan] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let live = true;
    setInfo(null);
    if (!variantId || !stockPointId) return undefined;
    api.get(`/stock-serials/available/?variant=${variantId}&stock_point=${stockPointId}`)
      .then((d) => { if (live) { setInfo(d); onInfo?.(d); } })
      .catch(() => { if (live) setInfo({ tracked: false, serials: [], untracked: 0 }); });
    return () => { live = false; };
  }, [variantId, stockPointId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!info || !info.tracked) return null;
  // units already on this invoice (a revision) stay pickable though they aren't "in stock" yet
  const options = [...new Set([...info.serials, ...value])];
  const need = Math.max(0, (+qty || 0) - info.untracked);
  const toggle = (sn) => onChange(value.includes(sn) ? value.filter((x) => x !== sn) : [...value, sn]);
  const addScanned = () => {
    const sn = scan.trim().toUpperCase();
    setScan("");
    if (!sn) return;
    if (!options.includes(sn)) { setNote(`${sn} is not in stock here for this item.`); return; }
    setNote("");
    if (!value.includes(sn)) onChange([...value, sn]);
  };
  const short = value.length < need;
  return (
    <div className="mt-1 rounded-lg p-2" style={{ border: `1px solid ${short ? C.amber : C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px]" style={{ fontFamily: F.body, color: short ? C.amber : C.inkSoft, fontWeight: 600 }}>
          Serial numbers · {value.length} picked · {need > 0 ? `${need} required` : "optional"}
          {info.untracked > 0 && <span style={{ fontWeight: 400 }}> ({info.untracked} unit{info.untracked === 1 ? " here has" : "s here have"} no serial and can go without one)</span>}
        </span>
        <label className="flex items-center gap-1 text-[11px]" style={{ color: C.inkSoft }}>
          <ScanLine size={12} />
          <input value={scan} onChange={(e) => setScan(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addScanned(); } }}
            placeholder="Scan / type serial + Enter" aria-label="Scan serial number" className="w-44 bg-transparent px-2 py-1 text-xs outline-none" style={{ fontFamily: F.mono, border: `1px solid ${C.rule}` }} />
        </label>
      </div>
      {note && <p className="mt-1 text-[11px]" style={{ color: C.carbon }}>{note}</p>}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {options.length === 0 && <span className="text-[11px]" style={{ color: C.inkSoft }}>No units with serial numbers in stock here.</span>}
        {options.map((sn) => {
          const on = value.includes(sn);
          return (
            <button key={sn} type="button" role="checkbox" aria-checked={on} onClick={() => toggle(sn)} className="rounded px-2 py-0.5 text-[11px]"
              style={{ fontFamily: F.mono, fontWeight: 700, border: `1px solid ${on ? C.stamp : C.rule}`, backgroundColor: on ? C.stamp : "transparent", color: on ? C.onAccent : C.ink }}>
              {sn}
            </button>
          );
        })}
      </div>
    </div>
  );
}
