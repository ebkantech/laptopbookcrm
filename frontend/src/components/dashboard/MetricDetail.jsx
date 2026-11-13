import { useEffect, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, Copy, MessageCircle, X } from "lucide-react";
import { api } from "../../lib/api";
import { copyText } from "../../lib/copyText";
import { toast } from "../../lib/toast";
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

const PAGE_SIZE = 50;

// "Copy reminder" / "Copy phone" on a row: the text comes ready from the server.
function CopyButtons({ items }) {
  const copy = async (item) => {
    try {
      await copyText(item.text);
      toast.success(item.primary ? "Reminder copied" : `${item.label.replace(/^Copy /, "")} copied`,
        item.primary ? "Paste it into the customer's WhatsApp chat." : item.text);
    } catch (e) {
      toast.error("Couldn't copy", e.message);
    }
  };
  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {items.map((item) => (
        <button key={item.label} type="button" onClick={() => copy(item)} title={item.text}
          className="inline-flex items-center gap-1 whitespace-nowrap px-2.5 py-1 text-[11px]"
          style={{ fontFamily: F.body, fontWeight: 700, borderRadius: 7,
            color: item.primary ? C.onAccent : C.ink, backgroundColor: item.primary ? C.green : C.slip,
            border: item.primary ? `1px solid ${C.green}` : `1px solid ${C.rule}` }}>
          {item.primary ? <MessageCircle size={12} /> : <Copy size={12} />} {item.label}
        </button>
      ))}
    </div>
  );
}

const PAGE_LABEL = { invoices: "Sales & Invoices", repairs: "Repairs", inventory: "Inventory", rentals: "Rentals" };

/*
 * Dashboard -> a metric card -> this: the records the figure is made of,
 * read with the same filters as the card (dates and store), so the total
 * at the bottom is the number on the card.
 */
export default function MetricDetail({ metric, filters, onClose, onGo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  // a different metric or filter starts again at page 1
  useEffect(() => { setPage(1); }, [metric, filters.dateFrom, filters.dateTo, filters.channel]);

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    if (filters.channel && filters.channel !== "all") params.set("channel", filters.channel);
    setLoading(true);
    api.get(`/dashboard/detail/${metric}/?${params}`)
      .then((d) => { setData(d); setError(""); }, (e) => setError(e.body?.detail || e.message))
      .finally(() => setLoading(false));
  }, [metric, filters.dateFrom, filters.dateTo, filters.channel, page]);

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
            {data.count} record{data.count === 1 ? "" : "s"}
            {data.pages > 1 && ` — showing ${(data.page_number - 1) * data.page_size + 1}–${(data.page_number - 1) * data.page_size + data.rows.length}`}
          </p>
          {data.rows.length ? (
            <div className="mt-2 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}`, opacity: loading ? 0.55 : 1, transition: "opacity 150ms" }} aria-busy={loading}>
              <table className={`w-full ${data.row_actions ? "min-w-[860px]" : "min-w-[640px]"} border-collapse`}>
                <thead style={{ backgroundColor: C.slip2 }}>
                  <tr>
                    {data.columns.map((c) => <th key={c.key} className={`px-3 py-2 text-[10px] uppercase text-${c.align}`} style={head}>{c.label}</th>)}
                    {data.row_actions && <th className="px-3 py-2 text-right text-[10px] uppercase" style={head}>Remind</th>}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={row.id ?? row.code ?? i} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, color: C.ink }}>
                      {data.columns.map((c) => (
                        <td key={c.key} className={`px-3 py-2 text-xs text-${c.align} ${c.kind === "date" || c.key === "phone" ? "whitespace-nowrap" : ""}`}
                          style={{ fontFamily: ["money", "number", "date"].includes(c.kind) || c.key === "code" || c.key === "agreement" ? F.mono : F.body,
                            fontWeight: c.key === data.total?.key || c.key === "code" ? 700 : 400,
                            color: c.key === "band" && row.at_risk ? C.carbon : c.key === "status" && row.status === "Overdue" ? C.carbon : undefined }}>
                          {show(row[c.key], c.kind)}
                          {c.key === "customer" && row.city && <span className="block text-[10px]" style={{ color: C.inkSoft }}>{[row.kind, row.city].filter(Boolean).join(" · ")}</span>}
                          {c.key === "oldest_due" && row.days_late > 0 && <span className="block text-[10px]" style={{ color: C.carbon }}>{row.days_late} day{row.days_late === 1 ? "" : "s"} late</span>}
                        </td>
                      ))}
                      {data.row_actions && <td className="px-3 py-2">{row.copy?.length ? <CopyButtons items={row.copy} /> : null}</td>}
                    </tr>
                  ))}
                </tbody>
                {data.total && (
                  <tfoot>
                    <tr style={{ borderTop: `2px solid ${C.ink}`, color: C.ink }}>
                      <td colSpan={data.columns.length - 1} className="px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 700 }}>
                        {data.total.label}{data.pages > 1 ? " (all pages)" : ""}
                      </td>
                      <td className="px-3 py-2 text-right text-xs" style={{ fontFamily: F.mono, fontWeight: 700 }}>{data.total.plain ? data.total.value : money(data.total.value)}</td>
                      {data.row_actions && <td />}
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          ) : (
            <p className="mt-6 text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Nothing here for this selection.</p>
          )}
          {data.pages > 1 && (
            <nav aria-label="Pages" className="mt-3 flex items-center justify-between gap-2 text-xs" style={{ fontFamily: F.body }}>
              <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}
                className="inline-flex min-h-[36px] items-center gap-1 px-3 disabled:opacity-40" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, fontWeight: 700, color: C.ink }}>
                <ChevronLeft size={14} /> Previous
              </button>
              <span style={{ color: C.inkSoft }}>Page <strong style={{ color: C.ink }}>{data.page_number}</strong> of {data.pages}</span>
              <button type="button" disabled={page >= data.pages || loading} onClick={() => setPage((p) => p + 1)}
                className="inline-flex min-h-[36px] items-center gap-1 px-3 disabled:opacity-40" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, fontWeight: 700, color: C.ink }}>
                Next <ChevronRight size={14} />
              </button>
            </nav>
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
