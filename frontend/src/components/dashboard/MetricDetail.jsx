import { useEffect, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, fmt, money } from "../../lib/theme";
import { ErrorNote, Spinner } from "../Atoms";

/* Shared popup frame for the dashboard's detail views. */
export function DetailFrame({ title, subtitle, onClose, children, wide = true }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4" style={{ backgroundColor: "rgba(4,9,18,0.6)" }} onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} data-panel
        className={`max-h-[92vh] w-full ${wide ? "max-w-4xl" : "max-w-2xl"} overflow-y-auto rounded-t-2xl p-5 sm:rounded-2xl sm:p-6`}
        style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{title}</p>
            {subtitle && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const show = (value, kind) => {
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "money") return money(value);
  if (kind === "date") return fmt(value);
  return String(value);
};

const PAGE_LABEL = { invoices: "Sales & Invoices", repairs: "Repairs", inventory: "Inventory", rentals: "Rentals" };

/*
 * Dashboard -> a metric card -> this: the records the figure is made of,
 * read with the same filters as the card (dates and store), so the total
 * at the bottom is the number on the card.
 */
export default function MetricDetail({ metric, filters, onClose, onGo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    if (filters.channel && filters.channel !== "all") params.set("channel", filters.channel);
    const qs = params.toString();
    api.get(`/dashboard/detail/${metric}/${qs ? `?${qs}` : ""}`).then(setData, (e) => setError(e.body?.detail || e.message));
  }, [metric, filters.dateFrom, filters.dateTo, filters.channel]);

  const head = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };
  const range = filters.dateFrom || filters.dateTo
    ? `${filters.dateFrom ? fmt(filters.dateFrom) : "start"} – ${filters.dateTo ? fmt(filters.dateTo) : "today"}` : "All dates";

  return (
    <DetailFrame title={data?.title || "Details"} subtitle={data ? `${data.subtitle} · ${range}${filters.channel && filters.channel !== "all" ? ` · ${filters.channel}` : ""}` : ""} onClose={onClose}>
      <ErrorNote message={error} />
      {!data && !error && <div className="py-10"><Spinner label="Loading the records behind this figure…" /></div>}
      {data && (
        <>
          <p className="mt-3 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            {data.count} record{data.count === 1 ? "" : "s"}{data.truncated ? ` — showing the first ${data.rows.length}` : ""}
          </p>
          {data.rows.length ? (
            <div className="mt-2 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
              <table className="w-full min-w-[640px] border-collapse">
                <thead style={{ backgroundColor: C.slip2 }}>
                  <tr>{data.columns.map((c) => <th key={c.key} className={`px-3 py-2 text-[10px] uppercase text-${c.align}`} style={head}>{c.label}</th>)}</tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={row.id ?? row.code ?? i} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, color: C.ink }}>
                      {data.columns.map((c) => (
                        <td key={c.key} className={`px-3 py-2 text-xs text-${c.align}`}
                          style={{ fontFamily: ["money", "number", "date"].includes(c.kind) || c.key === "code" || c.key === "agreement" ? F.mono : F.body,
                            fontWeight: c.key === data.total?.key || c.key === "code" ? 700 : 400,
                            color: c.key === "band" && row.at_risk ? C.carbon : c.key === "status" && row.status === "Overdue" ? C.carbon : undefined }}>
                          {show(row[c.key], c.kind)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
                {data.total && (
                  <tfoot>
                    <tr style={{ borderTop: `2px solid ${C.ink}`, color: C.ink }}>
                      <td colSpan={data.columns.length - 1} className="px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 700 }}>{data.total.label}</td>
                      <td className="px-3 py-2 text-right text-xs" style={{ fontFamily: F.mono, fontWeight: 700 }}>{data.total.plain ? data.total.value : money(data.total.value)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          ) : (
            <p className="mt-6 text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Nothing here for this selection.</p>
          )}
          {data.page && onGo && (
            <button type="button" onClick={() => { onClose(); onGo(data.page); }} className="mt-4 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 700, color: C.stamp }}>
              Open {PAGE_LABEL[data.page] || data.page} <ArrowRight size={13} />
            </button>
          )}
        </>
      )}
    </DetailFrame>
  );
}
