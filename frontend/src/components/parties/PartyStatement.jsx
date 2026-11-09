import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Printer } from "lucide-react";

import { api } from "../../lib/api";
import { C, F, fmt, money } from "../../lib/theme";
import { ErrorNote } from "../Atoms";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function periodText(data) {
  const { from, to, due } = data.filters || {};
  const range = from || to ? `${from ? fmt(from) : "Start"} to ${to ? fmt(to) : fmt(data.generated_on)}` : "All dates";
  return due ? `${range} · due invoices only` : range;
}

export function query(filters) {
  const params = new URLSearchParams();
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.due) params.set("due", "1");
  const text = params.toString();
  return text ? `?${text}` : "";
}

/* The statement as its own small page, printed from a hidden frame so the
 * popup and the rest of the app stay out of the printout. */
function printStatement(data) {
  const p = data.party;
  const rows = data.rows.map((r) => `<tr>
      <td>${escapeHtml(r.code)}<small>${escapeHtml(fmt(r.date))} · ${escapeHtml(r.kind)}${r.payments?.length ? ` · ${r.payments.length} part payment${r.payments.length > 1 ? "s" : ""}` : ""}</small></td>
      <td>${(r.items || []).map((i) => `${escapeHtml(i.name)} × ${i.qty}`).join("<br>") || "-"}</td><td class="n">${r.qty}</td><td class="n">${escapeHtml(money(r.amount))}</td><td class="n">${escapeHtml(money(r.paid))}</td>
      <td class="n">${escapeHtml(money(r.credit))}</td><td class="n b">${escapeHtml(money(r.balance))}</td></tr>`).join("");
  const t = data.totals;
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Statement - ${escapeHtml(p.name)}</title><style>
    body{font:12px Arial,sans-serif;color:#111;margin:24px}h1{font-size:18px;margin:0}p{margin:2px 0;color:#444}
    table{width:100%;border-collapse:collapse;margin-top:16px}th,td{border-bottom:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}
    th{background:#f2f2f2;font-size:11px}td small{display:block;color:#666;font-size:10px;margin-top:2px}.n{text-align:right;white-space:nowrap}.b{font-weight:bold}
    tfoot td{font-weight:bold;border-top:2px solid #111}@page{margin:12mm}</style></head><body>
    <h1>Customer statement</h1><p><b>${escapeHtml(p.name)}</b> · ${escapeHtml(p.phone)}${p.city ? ` · ${escapeHtml(p.city)}` : ""}${p.gstin ? ` · GSTIN ${escapeHtml(p.gstin)}` : ""}</p>
    <p>${escapeHtml(periodText(data))} · as on ${escapeHtml(fmt(data.generated_on))}</p>
    <table><thead><tr><th>Invoice</th><th>Items</th><th class="n">Qty</th><th class="n">Invoice amount</th><th class="n">Paid / advance</th><th class="n">Credit</th><th class="n">Balance</th></tr></thead>
    <tbody>${data.opening ? `<tr><td colspan="6">Opening balance</td><td class="n b">${escapeHtml(money(data.opening))}</td></tr>` : ""}${rows || '<tr><td colspan="7">No invoices for this selection.</td></tr>'}</tbody>
    <tfoot><tr><td>Total</td><td></td><td class="n">${t.qty}</td><td class="n">${escapeHtml(money(t.amount))}</td><td class="n">${escapeHtml(money(t.paid))}</td><td class="n">${escapeHtml(money(t.credit ?? t.balance))}</td><td class="n">${escapeHtml(money(t.balance))}</td></tr></tfoot>
    </table></body></html>`;
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(frame);
  const doc = frame.contentWindow.document;
  doc.open();
  doc.write(html);
  doc.close();
  frame.contentWindow.focus();
  frame.contentWindow.print();
  window.setTimeout(() => frame.remove(), 1000);
}

// Every invoice with its quantity, what was paid and what is still owed,
// ending in the running balance the customer owes.
export default function PartyStatement({ partyId, filters = {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  // Amount column: click for highest first, again for lowest first; null = date order
  const [amountSort, setAmountSort] = useState(null);
  const rows = useMemo(() => {
    const list = Array.isArray(data?.rows) ? [...data.rows] : [];
    if (amountSort) list.sort((a, b) => (amountSort === "desc" ? b.amount - a.amount : a.amount - b.amount));
    return list;
  }, [data, amountSort]);
  const filterQuery = query(filters);
  useEffect(() => {
    let live = true;
    setError("");
    api.get(`/parties/${partyId}/statement/${filterQuery}`)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(e.body?.detail || e.message); });
    return () => { live = false; };
  }, [partyId, filterQuery]);

  const download = async () => {
    setDownloading(true);
    setError("");
    try {
      const url = await api.blobUrl(`/parties/${partyId}/statement/pdf/${filterQuery}`);
      const link = document.createElement("a");
      link.href = url;
      link.download = `Statement-${(data?.party.name || "customer").replace(/[^A-Za-z0-9]+/g, "-")}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      setError("Couldn't download the statement. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  if (!data) return error ? <div className="mt-6"><ErrorNote message={error} /></div> : null;
  if (!Array.isArray(data.rows) || !data.totals) return <div className="mt-6"><ErrorNote message="The statement couldn't be read. Restart the server and try again." /></div>;
  const button = "flex h-10 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs disabled:opacity-40 sm:h-9";
  const buttonStyle = { fontFamily: F.body, fontWeight: 600, color: C.ink, border: `1px solid ${C.rule}`, backgroundColor: C.slip };
  const head = "px-2 py-2 text-[10px] uppercase";
  const headStyle = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", color: C.inkSoft };
  const cell = "px-2 py-2 text-right text-xs";
  return (
    <section aria-label="Customer statement" className="mt-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
          Statement — balance <span style={{ color: data.totals.balance > 0 ? C.carbon : C.green }}>{money(data.totals.balance)}</span>
        </p>
        <div className="flex shrink-0 gap-1.5">
          <button type="button" onClick={download} disabled={downloading} className={button} style={buttonStyle}>
            <Download size={14} /> {downloading ? "Preparing…" : "Download"}
          </button>
          <button type="button" onClick={() => printStatement(data)} className={button} style={buttonStyle}>
            <Printer size={14} /> Print
          </button>
        </div>
      </div>
      <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{periodText(data)} — set the filters on the Parties list.</p>
      {error && <div className="mt-2"><ErrorNote message={error} /></div>}
      {data.rows.length ? (
        <div className="mt-3 overflow-x-auto rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
          <table className="w-full min-w-[720px] border-collapse">
            <thead style={{ backgroundColor: C.slip2 }}>
              <tr>
                <th className={`${head} text-left`} style={headStyle}>Invoice</th>
                <th className={`${head} text-left`} style={headStyle}>Items</th>
                <th className={`${head} text-right`} style={headStyle}>Qty</th>
                <th className={`${head} text-right`} style={headStyle} aria-sort={amountSort === "desc" ? "descending" : amountSort === "asc" ? "ascending" : "none"}>
                  <button type="button" onClick={() => setAmountSort((v) => (v === "desc" ? "asc" : "desc"))}
                    title={amountSort === "desc" ? "Showing highest first — click for lowest first" : "Click to sort by amount, highest first"}
                    className="inline-flex items-center gap-1 uppercase" style={{ ...headStyle, color: amountSort ? C.stamp : C.inkSoft }}>
                    Amount {amountSort === "asc" ? <ArrowUp size={11} /> : amountSort === "desc" ? <ArrowDown size={11} /> : <ArrowUpDown size={11} />}
                  </button>
                </th>
                <th className={`${head} text-right`} style={headStyle}>Paid / advance</th>
                <th className={`${head} text-right`} style={headStyle}>Credit</th>
                <th className={`${head} text-right`} style={headStyle}>Balance</th>
              </tr>
            </thead>
            <tbody>
              {data.opening > 0 && !amountSort && (
                <tr style={{ borderTop: `1px solid ${C.rule}`, fontFamily: F.mono, color: C.ink }}>
                  <td colSpan={6} className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>Opening balance</td>
                  <td className={cell} style={{ fontWeight: 700 }}>{money(data.opening)}</td>
                </tr>
              )}
              {rows.map((r) => (
                <tr key={r.id} className="stmt-row" style={{ borderTop: `1px solid ${C.rule}`, fontFamily: F.mono, color: C.ink }}>
                  <td className="px-2 py-2 text-left text-xs">
                    <span style={{ fontWeight: 700 }}>{r.code}</span>
                    <span className="block text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>
                      {fmt(r.date)} · {r.kind}
                      {(r.payments || []).map((pay, i) => <span key={i} className="block">Part paid {money(pay.amount)} · {pay.pay_method} · {fmt(pay.paid_on)}</span>)}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>
                    {r.items?.length ? r.items.map((i, n) => <span key={n} className="block">{i.name} × {i.qty}</span>) : "—"}
                  </td>
                  <td className={cell}>{r.qty}</td>
                  <td className={cell}>{money(r.amount)}</td>
                  <td className={cell}>{money(r.paid)}</td>
                  <td className={cell} style={{ color: r.credit > 0 ? C.carbon : C.inkSoft }}>{money(r.credit)}</td>
                  <td className={cell} style={{ fontWeight: 700 }}>{money(r.balance)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: `2px solid ${C.ink}`, fontFamily: F.mono, fontWeight: 700, color: C.ink }}>
                <td className="px-2 py-2 text-left text-xs" style={{ fontFamily: F.body }}>Total</td>
                <td />
                <td className={cell}>{data.totals.qty}</td>
                <td className={cell}>{money(data.totals.amount)}</td>
                <td className={cell}>{money(data.totals.paid)}</td>
                <td className={cell}>{money(data.totals.credit ?? data.totals.balance)}</td>
                <td className={cell}>{money(data.totals.balance)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : <p className="mt-3 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No invoices for this selection.</p>}
      {amountSort && data.rows.length > 1 && (
        <p className="mt-1.5 text-[11px]" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Sorted by amount, {amountSort === "desc" ? "highest" : "lowest"} first. Balance is the running total in date order.{" "}
          <button type="button" onClick={() => setAmountSort(null)} className="underline" style={{ color: C.stamp, fontWeight: 600 }}>Back to date order</button>
        </p>
      )}
    </section>
  );
}
