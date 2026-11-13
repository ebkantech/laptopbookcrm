import { useEffect, useState } from "react";
import { AlertTriangle, PackageOpen } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

const days = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));

/* Stock that is out with technicians. Red = the job is over and the leftover
 * must come back; amber = still on a live job. Technicians see their own;
 * Admins see their store's team. Renders nothing when there is none. */
export default function PartsToReturn({ onOpenLead, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true;
    api.get("/leads/parts_due/").then((d) => { if (live) setData(d); }).catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [refreshKey]);
  if (!data || !data.items.length) return null;
  const due = data.items.filter((i) => i.due_now);
  const holding = data.items.filter((i) => !i.due_now);
  const Row = ({ i, hot }) => (
    <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1.5 text-sm" style={{ borderTop: `1px solid ${C.rule}` }}>
      <span className="min-w-0 break-words"><strong>{i.outstanding} × {i.description}</strong><span className="block text-xs" style={{ color: C.inkSoft }}>{i.technician_name} · held {days(i.issued_at)}d</span></span>
      {onOpenLead
        ? <button type="button" onClick={() => onOpenLead(i.lead)} className="text-xs underline" style={{ fontFamily: F.mono, color: hot ? C.carbon : C.inkSoft }}>{i.lead_code}</button>
        : <span className="text-xs" style={{ fontFamily: F.mono, color: hot ? C.carbon : C.inkSoft }}>{i.lead_code}</span>}
    </li>
  );
  return (
    <section aria-label="Parts to return" className="mt-4 p-4" style={{ border: `2px solid ${due.length ? C.carbon : C.amber}`, backgroundColor: due.length ? `color-mix(in srgb, ${C.carbon} 6%, transparent)` : `color-mix(in srgb, ${C.amber} 7%, transparent)` }}>
      <p className="flex items-center gap-2 text-sm" style={{ fontWeight: 700, color: due.length ? C.carbon : C.ink, fontFamily: F.body }}>
        {due.length ? <AlertTriangle size={16} /> : <PackageOpen size={16} />}
        {due.length ? `${due.length} item${due.length === 1 ? "" : "s"} to return to the store` : `${holding.length} item${holding.length === 1 ? "" : "s"} out with technicians`}
      </p>
      {due.length > 0 && <ul className="mt-2">{due.map((i) => <Row key={i.id} i={i} hot />)}</ul>}
      {holding.length > 0 && (
        <>
          {due.length > 0 && <p className="mt-3 text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.1em" }}>Still on open jobs</p>}
          <ul className="mt-1">{holding.map((i) => <Row key={i.id} i={i} />)}</ul>
        </>
      )}
    </section>
  );
}
