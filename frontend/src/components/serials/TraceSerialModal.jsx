import { useEffect, useState } from "react";
import { ScanLine, X } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, fmt, money } from "../../lib/theme";
import { ErrorNote, Pill } from "../Atoms";
import { SERIAL_STATUS_COLOR } from "./serialStatus";

const when = (v) => (v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

/* Scan or type a serial number and see the unit's whole life: product,
 * where it is now, who bought it, its warranty, repairs and every step. */
export default function TraceSerialModal({ onClose, initial = "" }) {
  const [q, setQ] = useState(initial);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const look = async (value = q) => {
    const sn = value.trim();
    if (!sn) return;
    setBusy(true); setError(""); setData(null);
    try { setData(await api.get(`/stock-serials/trace/?q=${encodeURIComponent(sn)}`)); }
    catch (e) { setError(e.body?.detail || e.message); }
    finally { setBusy(false); }
  };
  useEffect(() => { if (initial) look(initial); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const box = { border: `1px solid ${C.rule}`, backgroundColor: C.slip2 };
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center p-0 sm:items-center sm:p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div role="dialog" aria-label="Trace a serial number" data-panel className="max-h-[92vh] w-full max-w-2xl overflow-y-auto p-5 sm:p-6" style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.inkSoft }}>Trace a unit</span>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 items-center justify-center rounded-full"><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); look(); }}>
          <label className="flex flex-1 items-center gap-2 px-3 py-2" style={{ border: `1px solid ${C.rule}` }}>
            <ScanLine size={15} style={{ color: C.inkSoft }} />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Scan the label or type the serial number" aria-label="Serial number" className="w-full bg-transparent text-sm outline-none" style={{ fontFamily: F.mono }} />
          </label>
          <button type="submit" disabled={busy} className="px-4 text-xs" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700 }}>{busy ? "…" : "Trace"}</button>
        </form>
        <ErrorNote message={error} />
        {data && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-lg" style={{ fontFamily: F.mono, fontWeight: 700 }}>{data.serial_number}</p>
                <p className="text-sm" style={{ fontFamily: F.body }}>{data.product} · {data.spec}{data.colour ? `, ${data.colour}` : ""}</p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{data.product_code} · SKU {data.variant_code} · {data.stock_point}</p>
              </div>
              <Pill color={SERIAL_STATUS_COLOR[data.status]}>{data.status_label}</Pill>
            </div>
            {data.sale && (
              <div className="p-3 text-sm" style={box}>
                <p className="text-[10px] uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Sold</p>
                <p><b>{data.sale.customer}</b> <span style={{ fontFamily: F.mono, color: C.inkSoft }}>{data.sale.phone}</span></p>
                <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{data.sale.invoice} · {fmt(data.sale.date)} · {money(data.sale.price)} · {data.sale.invoice_status}</p>
              </div>
            )}
            {data.warranties.length > 0 && (
              <div className="p-3 text-sm" style={box}>
                <p className="text-[10px] uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Warranty</p>
                {data.warranties.map((w) => <p key={w.id}>{w.status} · ends {fmt(w.end_date)}{w.claims ? ` · ${w.claims} claim${w.claims === 1 ? "" : "s"}` : ""}</p>)}
              </div>
            )}
            {data.repairs.length > 0 && (
              <div className="p-3 text-sm" style={box}>
                <p className="text-[10px] uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Repairs</p>
                {data.repairs.map((t) => <p key={t.id}><span style={{ fontFamily: F.mono }}>{t.code}</span> · {t.status} · {fmt(t.received)}</p>)}
              </div>
            )}
            <div>
              <p className="text-[10px] uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>History</p>
              <ol className="mt-2 space-y-2 border-l pl-4" style={{ borderColor: C.rule }}>
                {data.events.map((e, i) => (
                  <li key={i} className="text-sm"><span className="block break-words">{e.text}</span>
                    <span className="text-xs" style={{ color: C.inkSoft }}>{when(e.at)}{e.store && ` · ${e.store}`}{e.by && ` · ${e.by}`}</span></li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
