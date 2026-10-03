import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Printer, X } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote, Eyebrow, Spinner } from "../Atoms";

// Indian numbering (lakh / crore) in words, for the "Amount in words"
// line every printed invoice carries.
const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
  "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

function belowHundred(n) {
  return n < 20 ? ONES[n] : `${TENS[Math.floor(n / 10)]}${n % 10 ? ` ${ONES[n % 10]}` : ""}`;
}

function belowThousand(n) {
  const h = Math.floor(n / 100);
  const rest = n % 100;
  return [h ? `${ONES[h]} Hundred` : "", rest ? belowHundred(rest) : ""].filter(Boolean).join(" ");
}

function amountInWords(amount) {
  let n = Math.round(Math.abs(amount || 0));
  if (n === 0) return "Rupees Zero Only";
  const parts = [];
  const crore = Math.floor(n / 10000000); n %= 10000000;
  const lakh = Math.floor(n / 100000); n %= 100000;
  const thousand = Math.floor(n / 1000); n %= 1000;
  if (crore) parts.push(`${belowThousand(crore)} Crore`);
  if (lakh) parts.push(`${belowHundred(lakh)} Lakh`);
  if (thousand) parts.push(`${belowHundred(thousand)} Thousand`);
  if (n) parts.push(belowThousand(n));
  return `Rupees ${parts.join(" ")} Only`;
}

// Fixed light colours on purpose: this is a paper document, so it must
// print the same whatever theme the app is in.
const INK = "#1a1a1a";
const SOFT = "#555";
const LINE = "#c9c9c9";
const cell = { padding: "6px 8px", borderBottom: `1px solid ${LINE}`, textAlign: "left", verticalAlign: "top" };
const num = { ...cell, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };

function InvoiceSheet({ data }) {
  const { invoice, seller, buyer, items } = data;
  const paid = invoice.status === "Paid";
  return (
    <div style={{ backgroundColor: "#fff", color: INK, fontFamily: "Arial, Helvetica, sans-serif", fontSize: 12, padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, borderBottom: `2px solid ${INK}`, paddingBottom: 12 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{seller.name}</div>
          <div style={{ marginTop: 2, fontWeight: 600 }}>{seller.branch}</div>
          {seller.address && <div style={{ whiteSpace: "pre-line", color: SOFT }}>{seller.address}</div>}
          <div style={{ color: SOFT }}>
            {[seller.phone && `Ph: ${seller.phone}`, seller.email].filter(Boolean).join(" · ")}
          </div>
          {seller.gstin && <div style={{ marginTop: 2 }}>GSTIN: <b>{seller.gstin}</b></div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: 1 }}>INVOICE</div>
          <div style={{ marginTop: 4 }}>No. <b>{invoice.code}</b></div>
          <div>Date: {fmt(invoice.date)}</div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginTop: 12 }}>
        <div>
          <div style={{ color: SOFT, fontSize: 10, textTransform: "uppercase", letterSpacing: 1 }}>Bill to</div>
          <div style={{ fontWeight: 700, marginTop: 2 }}>{buyer.name}</div>
          {buyer.city && <div>{buyer.city}</div>}
          <div style={{ color: SOFT }}>{[buyer.phone && `Ph: ${buyer.phone}`, buyer.email].filter(Boolean).join(" · ")}</div>
          {buyer.gstin && <div>GSTIN: <b>{buyer.gstin}</b></div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: SOFT, fontSize: 10, textTransform: "uppercase", letterSpacing: 1 }}>Sold from</div>
          <div style={{ fontWeight: 700, marginTop: 2 }}>{seller.branch}</div>
        </div>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
        <thead>
          <tr style={{ backgroundColor: "#f0f0f0" }}>
            <th style={{ ...cell, width: 28 }}>#</th>
            <th style={cell}>Item</th>
            <th style={cell}>HSN</th>
            <th style={{ ...num, width: 50 }}>Qty</th>
            <th style={{ ...num, width: 100 }}>Rate</th>
            <th style={{ ...num, width: 110 }}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.n}>
              <td style={cell}>{it.n}</td>
              <td style={cell}>
                <div style={{ fontWeight: 600 }}>{it.description}</div>
                <div style={{ color: SOFT, fontSize: 11 }}>{it.spec} · {it.code}</div>
              </td>
              <td style={cell}>{it.hsn || "—"}</td>
              <td style={num}>{it.qty}</td>
              <td style={num}>{money(it.rate)}</td>
              <td style={num}>{money(it.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td style={{ ...cell, borderBottom: `2px solid ${INK}` }} colSpan={3}><b>Total</b></td>
            <td style={{ ...num, borderBottom: `2px solid ${INK}` }}><b>{data.total_qty}</b></td>
            <td style={{ ...num, borderBottom: `2px solid ${INK}` }} />
            <td style={{ ...num, borderBottom: `2px solid ${INK}`, fontSize: 14 }}><b>{money(data.total)}</b></td>
          </tr>
        </tfoot>
      </table>

      <div style={{ marginTop: 8 }}>Amount in words: <b>{amountInWords(data.total)}</b></div>

      <div style={{ marginTop: 16, padding: 10, border: `1px solid ${LINE}` }}>
        {paid ? (
          <>
            <b>PAID</b> on {fmt(invoice.paid_on)} via {invoice.pay_method}
            {invoice.payment_reference && <> · Ref: {invoice.payment_reference}</>}
          </>
        ) : (
          <><b>Payment due:</b> {money(data.total)}</>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 48 }}>
        <div style={{ color: SOFT, fontSize: 11 }}>Thank you for your business. This is a computer-generated invoice.</div>
        <div style={{ textAlign: "center" }}>
          <div style={{ borderTop: `1px solid ${INK}`, paddingTop: 4, minWidth: 180 }}>For {seller.name}<br />Authorised signatory</div>
        </div>
      </div>
    </div>
  );
}

export default function PrintableInvoice({ invoiceId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/invoices/${invoiceId}/print-data/`).then(setData).catch((e) => setError(e.message));
  }, [invoiceId]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: `1px solid ${C.rule}` }}>
          <Eyebrow>Print invoice</Eyebrow>
          <div className="flex items-center gap-2">
            <button
              onClick={() => window.print()} disabled={!data}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase"
              style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", opacity: data ? 1 : 0.6 }}
            >
              <Printer size={13} /> Print / Save PDF
            </button>
            <button onClick={onClose}><X size={18} style={{ color: C.inkSoft }} /></button>
          </div>
        </div>
        <div className="overflow-y-auto p-4" style={{ backgroundColor: "#e9e9e9" }}>
          {error ? <ErrorNote message={error} /> : !data ? <Spinner label="Preparing invoice…" /> : <InvoiceSheet data={data} />}
        </div>
      </div>
      {/* The copy that actually prints: mounted straight under <body> so
          the modal's scroll container can't clip it to one screen. Hidden
          on screen; index.css shows only this when printing. */}
      {data && createPortal(<div id="print-invoice-root"><InvoiceSheet data={data} /></div>, document.body)}
    </div>
  );
}
