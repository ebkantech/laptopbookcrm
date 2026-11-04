import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowDownWideNarrow, ArrowUpNarrowWide, Check, ChevronDown, Copy, Lock, PackageOpen, RefreshCw, Repeat2 } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { copyText } from "../../lib/copyText";
import { useSession } from "../../context/SessionContext";
import { Pill } from "../Atoms";

const STATUS_COLOR = { Paid: C.green, "Payment link sent": C.amber, Overdue: C.carbon, Cancelled: C.inkSoft, Refunded: "#7C6FD8" };
// sales.models.Invoice.OUTSTANDING -- still owed, and owed in full: settling an invoice always marks all of it paid.
const OUTSTANDING = ["Payment link sent", "Overdue"];

// "desc" is newest first -- the backend's own order: invoice date, then id for
// invoices raised the same day. An invoice without a date always sorts last.
function sortInvoices(invoices, direction) {
  const sign = direction === "desc" ? -1 : 1;
  return [...invoices].sort((a, b) => {
    if (!a.date !== !b.date) return a.date ? -1 : 1;
    const byDate = a.date && b.date ? a.date.localeCompare(b.date) : 0;
    return sign * (byDate || a.id - b.id);
  });
}

const itemName = (item) => item.product || item.product_name || "Item";
const variantOf = (item) => [item.spec, item.colour].filter(Boolean).join(", ");

// Plain text, one field per line, so it pastes cleanly into WhatsApp, email or a spreadsheet.
function itemText(item) {
  return [
    `${item.variant ? "Product" : "Item"}: ${itemName(item)}`,
    item.variant_code && `Product ID: ${item.variant_code}`,
    variantOf(item) && `Variant: ${variantOf(item)}`,
    `Quantity: ${item.qty}`,
    `Unit Price: ${money(item.price)}`,
    `Item Total: ${money(item.line_total)}`,
    item.returned_qty > 0 && `Returned: ${item.returned_qty}`,
  ].filter(Boolean).join("\n");
}

function invoiceItemsText(data) {
  return [
    `Invoice: ${data.code}`,
    `Date: ${fmt(data.date)}`,
    `Items: ${data.items.length}`,
    "",
    data.items.map((item, index) => `Item ${index + 1}\n${itemText(item)}`).join("\n\n"),
    "",
    `Invoice Total: ${money(data.total)}`,
  ].join("\n");
}

function loadError(error) {
  if (error.status === 403) return "Your role needs Invoices view permission to see invoice items.";
  if (error.status === 404) return "This invoice is no longer available. Refresh the customer record.";
  return error.message || "Couldn't load the items on this invoice.";
}

function CopyButton({ label, state, disabled = false, onClick }) {
  const copied = state === "ok";
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={disabled ? "No items to copy" : copied ? "Copied" : label} aria-label={label}
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-40 sm:h-8 sm:w-8"
      style={{ color: copied ? C.green : C.inkSoft }}>
      {copied ? <Check size={15} /> : <Copy size={15} />}
    </button>
  );
}

// The party popup's invoice list: sortable, and each invoice expands in place to its own line
// items, fetched once per popup session from GET /parties/<id>/invoices/<invoice>/items/.
export default function PartyInvoices({ partyId, invoices, invoiceCount, totalSpent }) {
  const { can } = useSession();
  const canSeeItems = can("invoices.view");
  const [direction, setDirection] = useState("desc");
  const [expanded, setExpanded] = useState(() => new Set());
  // { [invoiceId]: { status: "loading" | "ready" | "error", data, error } }
  const [itemsById, setItemsById] = useState({});
  const inFlight = useRef(new Set());
  // { [copyKey]: "ok" | error message } -- cleared 2 s after each copy
  const [copied, setCopied] = useState({});
  const copyTimers = useRef({});

  useEffect(() => () => Object.values(copyTimers.current).forEach((id) => window.clearTimeout(id)), []);

  const loadItems = (invoiceId) => {
    if (inFlight.current.has(invoiceId)) return;
    inFlight.current.add(invoiceId);
    setItemsById((current) => ({ ...current, [invoiceId]: { status: "loading" } }));
    api.get(`/parties/${partyId}/invoices/${invoiceId}/items/`)
      .then((data) => setItemsById((current) => ({ ...current, [invoiceId]: { status: "ready", data } })))
      .catch((error) => setItemsById((current) => ({ ...current, [invoiceId]: { status: "error", error: loadError(error) } })))
      .finally(() => inFlight.current.delete(invoiceId));
  };

  const toggle = (invoiceId) => {
    const opening = !expanded.has(invoiceId);
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(invoiceId)) next.delete(invoiceId); else next.add(invoiceId);
      return next;
    });
    const cached = itemsById[invoiceId];
    if (opening && canSeeItems && (!cached || cached.status === "error")) loadItems(invoiceId);
  };

  const copy = async (event, key, text) => {
    // copy icons sit inside an expanded invoice: never let the click reach its toggle
    event.stopPropagation();
    window.clearTimeout(copyTimers.current[key]);
    let result = "ok";
    try { await copyText(text); }
    catch { result = "Couldn't copy: the browser blocked clipboard access."; }
    setCopied((current) => ({ ...current, [key]: result }));
    copyTimers.current[key] = window.setTimeout(() => setCopied((current) => ({ ...current, [key]: "" })), 2000);
  };

  const newestFirst = direction === "desc";
  const SortIcon = newestFirst ? ArrowDownWideNarrow : ArrowUpNarrowWide;
  const sortTip = newestFirst
    ? "Sorted by date: newest invoice first. Click to show oldest first."
    : "Sorted by date: oldest invoice first. Click to show newest first.";
  const sorted = sortInvoices(invoices, direction);
  const controlClass = "flex h-10 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs transition-colors hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-40 sm:h-9";
  const controlStyle = { fontFamily: F.body, fontWeight: 600, color: C.ink, border: `1px solid ${C.rule}`, backgroundColor: C.slip };

  const renderItems = (invoice) => {
    if (!canSeeItems) return (
      <p className="flex items-center gap-2 px-4 py-4 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        <Lock size={13} />Your role needs Invoices view permission to see the items on this invoice.
      </p>
    );
    const entry = itemsById[invoice.id];
    if (!entry || entry.status === "loading") return (
      <div role="status" className="flex items-center gap-2.5 px-4 py-5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        <span className="spinner-border spinner-border-sm" aria-hidden="true" style={{ color: C.orange }} />Loading items…
      </div>
    );
    if (entry.status === "error") return (
      <div role="alert" className="flex flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>
        <span className="flex min-w-0 items-center gap-2"><AlertTriangle size={13} className="shrink-0" />{entry.error}</span>
        <button type="button" onClick={(event) => { event.stopPropagation(); loadItems(invoice.id); }} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-semibold hover:bg-black/5" style={{ border: `1px solid ${C.rule}`, color: C.ink }}>
          <RefreshCw size={12} />Retry
        </button>
      </div>
    );

    const { data } = entry;
    const allKey = `all-${invoice.id}`;
    const copyStates = data.items.map((item) => copied[`item-${item.id}`]).concat(copied[allKey]);
    const copyError = copyStates.find((state) => state && state !== "ok");
    return <>
      <div className="flex items-center justify-between gap-2 py-1.5 pl-4 pr-2" style={{ borderBottom: `1px solid ${C.rule}` }}>
        <p className="text-[11px] uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.12em", color: C.inkSoft }}>
          {data.items.length} item{data.items.length !== 1 ? "s" : ""}
        </p>
        <CopyButton label="Copy all items" state={copied[allKey]} disabled={!data.items.length} onClick={(event) => copy(event, allKey, invoiceItemsText(data))} />
      </div>
      {data.items.length ? <>
        <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_3rem_6.5rem_7rem_2rem] gap-x-3 px-4 pt-2 text-[10px] uppercase sm:grid" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", color: C.inkSoft }}>
          <span>Item</span><span className="text-right">Qty</span><span className="text-right">Unit price</span><span className="text-right">Amount</span><span />
        </div>
        <ul>
          {data.items.map((item, index) => {
            const key = `item-${item.id}`;
            const meta = [item.variant_code, variantOf(item)].filter(Boolean).join(" · ");
            return (
              <li key={item.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 py-2.5 pl-4 pr-2 sm:grid-cols-[minmax(0,1fr)_3rem_6.5rem_7rem_2rem] sm:items-center sm:pr-4" style={{ borderTop: index ? `1px solid ${C.rule}` : undefined }}>
                <div className="min-w-0">
                  <p className="break-words text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{itemName(item)}</p>
                  {meta && <p className="mt-0.5 break-all text-[11px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>{meta}</p>}
                  {item.returned_qty > 0 && <span className="mt-1 inline-flex"><Pill color={STATUS_COLOR.Refunded}>{item.returned_qty} returned</Pill></span>}
                  <p className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs sm:hidden" style={{ fontFamily: F.mono, color: C.inkSoft }}>
                    <span>{item.qty} × {money(item.price)}</span>
                    <span style={{ fontWeight: 700, color: C.ink }}>{money(item.line_total)}</span>
                  </p>
                </div>
                <span className="hidden text-right text-xs sm:block" style={{ fontFamily: F.mono, color: C.ink }}>{item.qty}</span>
                <span className="hidden text-right text-xs sm:block" style={{ fontFamily: F.mono, color: C.ink }}>{money(item.price)}</span>
                <span className="hidden text-right text-sm sm:block" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(item.line_total)}</span>
                <CopyButton label={`Copy ${itemName(item)}`} state={copied[key]} onClick={(event) => copy(event, key, itemText(item))} />
              </li>
            );
          })}
        </ul>
        <div className="flex items-baseline justify-end gap-3 px-4 py-2 text-xs" style={{ borderTop: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
          Invoice total<span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(data.total)}</span>
        </div>
      </> : (
        <p className="flex items-center gap-2 px-4 py-5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          <PackageOpen size={14} />No items are recorded on this invoice.
        </p>
      )}
      <p role="status" className={copyError ? "px-4 pb-2 text-xs" : "sr-only"} style={{ fontFamily: F.body, color: C.carbon }}>
        {copyError || (copyStates.includes("ok") ? "Copied" : "")}
      </p>
    </>;
  };

  return (
    <section aria-label="Transaction history">
      <div className="mt-6 flex items-center justify-between gap-3">
        <p className="min-w-0 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
          Transaction history — {invoiceCount} invoice{invoiceCount !== 1 ? "s" : ""}, {money(totalSpent)} total
        </p>
        <div className="flex shrink-0 items-center gap-1.5">
          <button type="button" onClick={() => setDirection((current) => (current === "desc" ? "asc" : "desc"))} disabled={invoices.length < 2}
            title={sortTip} aria-label={sortTip} className={controlClass} style={controlStyle}>
            <SortIcon size={15} /><span className="hidden sm:inline">{newestFirst ? "Newest first" : "Oldest first"}</span>
          </button>
        </div>
      </div>

      <ul className="mt-3 space-y-2">
        {sorted.map((invoice) => {
          const open = expanded.has(invoice.id);
          const owed = OUTSTANDING.includes(invoice.status);
          const color = STATUS_COLOR[invoice.status] || C.inkSoft;
          return (
            <li key={invoice.id} className="overflow-hidden rounded-xl" style={{ backgroundColor: C.slip2, border: `1px solid ${open ? `${C.stamp}55` : "transparent"}` }}>
              <button type="button" onClick={() => toggle(invoice.id)} aria-expanded={open} aria-controls={`party-invoice-items-${invoice.id}`}
                className="flex w-full min-w-0 items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-black/[0.03]"
                style={{ borderRadius: 0, backgroundColor: "transparent" }}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="break-all text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{invoice.code}</span>
                    {invoice.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{invoice.recurring_interval}</Pill>}
                  </div>
                  <p className="mt-0.5 break-words text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                    {invoice.date ? fmt(invoice.date) : "No date"} · {invoice.stock_point_name} · {invoice.item_count} item{invoice.item_count !== 1 ? "s" : ""}{invoice.pay_method ? ` · ${invoice.pay_method}` : ""}
                  </p>
                  {owed && <p className="mt-1 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: invoice.status === "Overdue" ? C.carbon : C.amber }}>
                    Due {money(invoice.total)}{invoice.due_date ? ` · by ${fmt(invoice.due_date)}` : ""}
                  </p>}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-2">
                  <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(invoice.total)}</span>
                  <Pill color={color}>{invoice.status}</Pill>
                </div>
                <ChevronDown size={16} aria-hidden="true" className="shrink-0 transition-transform" style={{ color: C.inkSoft, transform: open ? "rotate(180deg)" : "none" }} />
              </button>
              {open && <div id={`party-invoice-items-${invoice.id}`} role="region" aria-label={`Items on ${invoice.code}`} style={{ borderTop: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
                {renderItems(invoice)}
              </div>}
            </li>
          );
        })}
        {!invoices.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No purchases recorded yet.</p>}
      </ul>
    </section>
  );
}
