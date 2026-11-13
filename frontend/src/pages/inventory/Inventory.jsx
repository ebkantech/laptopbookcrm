import { useEffect, useRef, useState } from "react";
import JsBarcode from "jsbarcode";
import {
  Check, Loader2, MapPin, Pencil, Plus, Printer, ScanBarcode, ScanLine, Search, X,
} from "lucide-react";
import { C, F, money } from "../lib/theme";
import { api } from "../lib/api";
import { onStoreChanged } from "../lib/storeEvents";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, PillButton, SearchInput, Spinner } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
// Add stock -- New product / Existing product (restock): inventory/AddStockModal.jsx
import AddStockModal from "./inventory/AddStockModal";
import TraceSerialModal from "../components/serials/TraceSerialModal";
import { SERIAL_STATUS_COLOR } from "../components/serials/serialStatus";
import { printSerialLabels } from "../components/serials/serialLabels";
import Prompt from "../components/leads/Prompt";

const STOCK_LABELS = { kb: "Karol Bagh", np: "Nehru Place", ln: "Lajpat Nagar", amazon: "Amazon", flipkart: "Flipkart", site: "Website", wa: "WhatsApp" };
const stockLabel = (s) => s.stock_point_name || STOCK_LABELS[s.stock_point] || s.stock_point;

/* Per shop/channel, across all of a product's variants: units held and
 * the distinct in-shop places (rack/shelf) they sit in. Only places
 * that actually hold stock are listed. */
function stockByLocation(product) {
  const byPoint = new Map();
  for (const v of product.variants) {
    for (const s of v.stock) {
      if (s.quantity <= 0) continue;
      const row = byPoint.get(s.stock_point) || { label: stockLabel(s), quantity: 0, places: new Set() };
      row.quantity += s.quantity;
      if (s.location) row.places.add(s.location);
      byPoint.set(s.stock_point, row);
    }
  }
  // Shops with a recorded place first (that's what someone looking for
  // the item needs), then by how many units each holds.
  return [...byPoint.values()].sort((a, b) => (b.places.size > 0) - (a.places.size > 0) || b.quantity - a.quantity);
}

function StockLocationCell({ product }) {
  const rows = stockByLocation(product);
  if (!rows.length) return <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Out of stock</span>;
  const shown = rows.slice(0, 2);
  const describe = (r) => `${r.label} (${r.quantity})${r.places.size ? ` — ${[...r.places].join(", ")}` : ""}`;
  return (
    <span className="block min-w-0 space-y-1" title={rows.map(describe).join("\n")}>
      {shown.map((r) => (
        <span key={r.label} className="flex min-w-0 items-start gap-1 text-xs" style={{ fontFamily: F.body }}>
          <MapPin size={11} className="mt-0.5" style={{ color: r.places.size ? C.stamp : C.inkSoft, flexShrink: 0 }} />
          <span className="min-w-0">
            <span className="block truncate" style={{ color: C.ink }}>
              {r.label} <span style={{ fontFamily: F.mono, color: C.inkSoft }}>({r.quantity})</span>
            </span>
            <span className="block truncate" style={{ color: r.places.size ? C.ink : C.inkSoft, fontWeight: r.places.size ? 600 : 400 }}>
              {r.places.size ? [...r.places].join(", ") : "No location set"}
            </span>
          </span>
        </span>
      ))}
      {rows.length > shown.length && (
        <span className="block text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>+{rows.length - shown.length} more</span>
      )}
    </span>
  );
}

/* Column name shown above a value on phones, where the table header row
 * is hidden. */
function MobileLabel({ children }) {
  return (
    <span className="mb-0.5 block text-[10px] uppercase md:hidden" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft }}>
      {children}
    </span>
  );
}

/* A variant's units with serial numbers (GET /products/<id>/serials/,
 * limited to the account's store). Each unit: the product's one Product ID,
 * its own Serial Number, and -- under it, when the product has one -- the
 * product's HSN code. Units received before serial numbers have none. */
function UnitList({ serials, productCode, hsn, inStock, product, variant, canEdit, onChanged, onTrace }) {
  const [showAll, setShowAll] = useState(false);
  const [writing, setWriting] = useState(null);
  if (!serials) return <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading serial numbers…</p>;
  const label = { fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft };
  const onShelf = serials.filter((s) => s.status === "in_stock");
  const shown = showAll ? serials : onShelf;
  const gone = serials.length - onShelf.length;
  const small = { fontFamily: F.body, fontWeight: 600, border: `1px solid ${C.rule}`, color: C.inkSoft };
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] uppercase" style={label}>
          Units in stock with serial numbers · {onShelf.length}{inStock > onShelf.length ? ` of ${inStock}` : ""}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {gone > 0 && <button type="button" onClick={() => setShowAll((v) => !v)} className="px-2 py-1 text-[11px]" style={small}>{showAll ? "In stock only" : `Show all (${gone} sold / out)`}</button>}
          {onShelf.length > 0 && (
            <button type="button" onClick={() => printSerialLabels(onShelf.map((s) => s.serial_number), { product: product.display_name, spec: variant.spec, productCode })}
              className="flex items-center gap-1 px-2 py-1 text-[11px]" style={small}><Printer size={11} /> Labels for {onShelf.length} in stock</button>
          )}
        </div>
      </div>
      {shown.length ? (
        <ul className="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2" aria-label="Units">
          {shown.map((s) => (
            <li key={s.serial_number} className="rounded-lg px-2.5 py-1.5 text-xs" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}
              title={`${s.stock_point} · received ${new Date(s.received_at).toLocaleDateString("en-IN")}`}>
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0">
                  <span className="block text-[10px] uppercase" style={label}>Serial number</span>
                  <button type="button" onClick={() => onTrace(s.serial_number)} className="block underline-offset-2 hover:underline" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }} title="Trace this unit">{s.serial_number}</button>
                  {hsn && <span className="block" style={{ fontFamily: F.mono, color: C.inkSoft }}>HSN {hsn} · {productCode}</span>}
                  {s.invoice && <span className="block" style={{ fontFamily: F.mono, color: C.inkSoft }}>{s.invoice}{s.customer ? ` · ${s.customer}` : ""}</span>}
                </span>
                <Pill color={SERIAL_STATUS_COLOR[s.status] || C.inkSoft}>{s.status_label || "In stock"}</Pill>
              </div>
              {s.status === "in_stock" && (
                <div className="mt-1 flex gap-1.5">
                  <button type="button" onClick={() => printSerialLabels([s.serial_number], { product: product.display_name, spec: variant.spec, productCode })} className="flex items-center gap-1 px-1.5 py-0.5 text-[11px]" style={small}><Printer size={10} /> Label</button>
                  {canEdit && <button type="button" onClick={() => setWriting(s)} className="px-1.5 py-0.5 text-[11px]" style={{ ...small, color: C.carbon }}>Write off</button>}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {inStock > onShelf.length && (
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          {inStock - onShelf.length} {inStock - onShelf.length === 1 ? "unit was" : "units were"} received before serial numbers were generated, so {inStock - onShelf.length === 1 ? "it has" : "they have"} none. They can be sold without a serial.
        </p>
      )}
      {onShelf.length > inStock && (
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>
          {onShelf.length - inStock} more serial{onShelf.length - inStock === 1 ? "" : "s"} marked in stock than units on the shelf — they left before tracking. Find which aren't here and write them off (without reducing stock).
        </p>
      )}
      {writing && (
        <Prompt title={`Write off ${writing.serial_number}`} tone={C.carbon}
          intro="Use this for a unit that is no longer on the shelf. Its history is kept."
          fields={[{ name: "reason", label: "What happened (lost, damaged, sold before tracking…)", required: true },
            { name: "reduce_stock", label: "Also take 1 off the shelf quantity (the unit is leaving now — lost or damaged)", type: "checkbox" }]}
          submitLabel="Write off" onClose={() => setWriting(null)}
          onSubmit={async (v) => {
            try { await api.post(`/stock-serials/${writing.id}/write_off/`, { reason: v.reason, reduce_stock: !!v.reduce_stock }); }
            catch (e) { throw new Error(e.body?.detail || e.body?.reason || e.message); }
            setWriting(null);
            onChanged();
          }} />
      )}
    </div>
  );
}

/* One shop's stock of one variant in the detail panel: quantity plus
 * where it sits, editable in place for inventory.edit holders. */
function StockTile({ stock, canEdit, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(stock.location || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const updated = await api.patch(`/inventory/stock/${stock.id}/location/`, { location: value.trim() });
      onSaved(updated);
      setEditing(false);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-2 py-1.5 rounded-xl" style={{ backgroundColor: C.slip2 }}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{stockLabel(stock)}</span>
        <span className="text-xs" style={{ fontFamily: F.mono, fontWeight: 600, color: stock.quantity <= 1 ? C.carbon : C.ink }}>{stock.quantity}</span>
      </div>
      {editing ? (
        <div className="mt-1 flex items-center gap-1">
          <input
            autoFocus value={value} maxLength={80} placeholder="Rack A / Shelf 3"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
            className="min-w-0 flex-1 bg-transparent px-1.5 py-0.5 text-xs outline-none"
            style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}
          />
          <button onClick={save} disabled={busy} title="Save location"><Check size={13} style={{ color: C.green }} /></button>
          <button onClick={() => { setEditing(false); setValue(stock.location || ""); }} title="Cancel"><X size={13} style={{ color: C.inkSoft }} /></button>
        </div>
      ) : (
        <div className="mt-0.5 flex items-center gap-1">
          <MapPin size={10} style={{ color: C.inkSoft, flexShrink: 0 }} />
          <span className="truncate text-xs" style={{ fontFamily: F.body, color: stock.location ? C.ink : C.inkSoft }}>
            {stock.location || "No location set"}
          </span>
          {canEdit && (
            <button onClick={() => setEditing(true)} className="ml-auto" title="Edit location"><Pencil size={11} style={{ color: C.inkSoft }} /></button>
          )}
        </div>
      )}
      {error && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>{error}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Barcode scan -- a real Bluetooth/USB scanner behaves like a
 *  keyboard: it types the code into whatever field is focused, then
 *  sends Enter. This box just needs to be focused and listening.
 * ------------------------------------------------------------------ */
function ScanModal({ onClose, onFound }) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState("ready"); // ready | searching | notfound
  const [error, setError] = useState("");

  const lookup = async (value) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setStatus("searching");
    setError("");
    try {
      const product = await api.get(`/products/lookup/?code=${encodeURIComponent(trimmed)}`);
      onFound(product);
    } catch (e) {
      setStatus("notfound");
      setError(e.status === 404 ? `No product or variant matches "${trimmed}".` : e.message);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "#040912b3" }}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>Barcode scanner</Eyebrow>
          <button type="button" onClick={onClose} aria-label="Close barcode scanner"><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        <div className="mt-6 flex flex-col items-center gap-4 py-4">
          <ScanBarcode size={36} style={{ color: status === "searching" ? C.orange : C.stamp }} />
          <p className="text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
            Scan a product label, or type the code below and press Enter.
          </p>
          <input
            autoFocus value={code}
            onChange={(e) => { setCode(e.target.value); setStatus("ready"); }}
            onKeyDown={(e) => e.key === "Enter" && lookup(code)}
            placeholder="VC-LAP-0001 or VC-SKU-0001"
            className="w-full bg-transparent px-3 py-2 text-center text-sm outline-none"
            style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${status === "notfound" ? C.carbon : C.rule}` }}
          />
          {status === "searching" && <p className="flex items-center gap-1.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}><Loader2 size={12} className="animate-spin" />Looking up…</p>}
          {status === "notfound" && <ErrorNote message={error} />}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Print label -- previews a sticker and hands off to the browser's
 *  print dialog, where the physical magnetic/thermal label printer is
 *  picked as the destination (a web app can't drive that hardware
 *  directly without a local print-agent, so this is the realistic
 *  boundary of what's possible from here).
 * ------------------------------------------------------------------ */
function PrintModal({ product, variant, onClose }) {
  const barcodeRef = useRef(null);
  const [barcodeError, setBarcodeError] = useState("");

  useEffect(() => {
    if (!barcodeRef.current || !variant?.code) {
      setBarcodeError("Variant code is missing, so a barcode cannot be generated.");
      return;
    }

    try {
      JsBarcode(barcodeRef.current, String(variant.code), {
        format: "CODE128",
        lineColor: "#171634",
        background: "#FFFFFF",
        width: 2,
        height: 42,
        margin: 2,
        displayValue: false,
      });
      setBarcodeError("");
    } catch (error) {
      console.error("Barcode generation failed:", error);
      setBarcodeError("Barcode could not be generated for this product code.");
    }
  }, [variant?.code]);

  const handlePrint = () => {
    if (!barcodeRef.current || !variant?.code || barcodeError) {
      window.alert(barcodeError || "Barcode is not ready yet. Please try again.");
      return;
    }

    // Open the print window directly from the button click so browsers
    // are less likely to block it as a popup.
    const printWindow = window.open("", "_blank", "width=500,height=400");
    if (!printWindow) {
      window.alert("The print window was blocked. Please allow pop-ups for this site and try again.");
      return;
    }

    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);

    const barcode = barcodeRef.current.cloneNode(true);
    barcode.setAttribute("class", "barcode");
    barcode.removeAttribute("style");

    const productName = escapeHtml(product.display_name);
    const variantSpec = escapeHtml(variant.spec || "Standard");
    const variantCode = escapeHtml(variant.code);
    const hsnText = product.hsn
      ? `HSN ${escapeHtml(product.hsn)}`
      : "Internal code — no HSN";
    const priceText = escapeHtml(money(variant.sell_price));

    printWindow.document.open();
    printWindow.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Product Sticker - ${productName}</title>
  <style>
    @page { size: 60mm 40mm; margin: 2mm; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #fff; color: #171634; }
    body { font-family: Arial, Helvetica, sans-serif; }
    .label {
      width: 56mm;
      min-height: 36mm;
      padding: 1mm;
      overflow: hidden;
      text-align: center;
      background: #fff;
      break-inside: avoid;
    }
    .brand { margin: 0 0 1mm; text-align: left; font-size: 8pt; font-weight: 700; }
    .product { margin: 1mm 0; font-size: 10pt; line-height: 1.15; font-weight: 700; overflow-wrap: anywhere; }
    .spec { margin: 0 0 1mm; font-size: 7pt; overflow-wrap: anywhere; }
    .barcode { display: block; width: 100%; max-width: 54mm; height: 12mm; margin: 1mm auto; }
    .code { margin: 0; font-family: monospace; font-size: 8pt; font-weight: 700; overflow-wrap: anywhere; }
    .details { margin: 1mm 0 0; font-size: 7pt; overflow-wrap: anywhere; }
    @media screen {
      body { padding: 10px; }
      .label { border: 1px dashed #aaa; }
    }
  </style>
</head>
<body>
  <main class="label">
    <p class="brand">Vantage Computers</p>
    <p class="product">${productName}</p>
    <p class="spec">${variantSpec}</p>
    ${barcode.outerHTML}
    <p class="code">${variantCode}</p>
    <p class="details">${hsnText} · ${priceText}</p>
  </main>
</body>
</html>`);
    printWindow.document.close();
    // Printed from here, not by a script inside the label page: the site's
    // Content-Security-Policy (public/_headers) blocks inline scripts there.
    printWindow.addEventListener("afterprint", () => printWindow.close());
    setTimeout(() => { printWindow.focus(); printWindow.print(); }, 250);
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[90vh] w-full max-w-sm overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>Label printer</Eyebrow>
          <button type="button" onClick={onClose} aria-label="Close label printer">
            <X size={16} style={{ color: C.inkSoft }} />
          </button>
        </div>

        <div className="mt-4 p-3" style={{ border: "1px dashed #B9C2CE", backgroundColor: "#FFFFFF" }}>
          <p className="text-xs" style={{ fontFamily: F.mono, color: "#5B5F52" }}>Vantage Computers</p>
          <p className="mt-1 text-sm break-words" style={{ fontFamily: F.display, fontWeight: 600, color: "#171634" }}>{product.display_name}</p>
          <p className="text-xs break-words" style={{ fontFamily: F.body, color: "#5B5F52" }}>{variant.spec || "Standard"}</p>
          <div className="mt-2 flex min-h-[52px] items-center justify-center overflow-hidden">
            <svg ref={barcodeRef} style={{ maxWidth: "100%", height: 52 }} aria-label={`Barcode for ${variant.code}`} />
          </div>
          {barcodeError && <p className="mt-2 text-xs" style={{ color: C.carbon, fontFamily: F.body }}>{barcodeError}</p>}
          <p className="mt-1 text-center text-xs break-all" style={{ fontFamily: F.mono, color: "#171634" }}>{variant.code}</p>
          <p className="text-center text-xs" style={{ fontFamily: F.mono, color: "#5B5F52" }}>
            {product.hsn ? `HSN ${product.hsn}` : "Internal code — no HSN"} · {money(variant.sell_price)}
          </p>
        </div>

        <button type="button" onClick={handlePrint} disabled={!!barcodeError} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase disabled:cursor-not-allowed disabled:opacity-50" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
          <Printer size={13} /> Print sticker
        </button>
        <p className="mt-2 text-center text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Choose your thermal or label printer in the print dialog. Default label size: 60 × 40 mm.
        </p>
      </div>
    </div>
  );
}

export default function Inventory() {
  const { can } = useSession();
  const [products, setProducts] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [openProduct, setOpenProduct] = useState(null);
  // serial numbers of the open product, by variant SKU: { productId, byVariant }
  const [openSerials, setOpenSerials] = useState({ productId: null, byVariant: {} });
  const [serialsVersion, setSerialsVersion] = useState(0);
  const [tracing, setTracing] = useState(null); // "" = open empty, or a serial number
  useEffect(() => {
    if (!openProduct) return undefined;
    let live = true;
    api.get(`/products/${openProduct.id}/serials/`).then((d) => {
      if (!live) return;
      const byVariant = {};
      for (const s of d.serials) (byVariant[s.variant] ||= []).push(s);
      setOpenSerials({ productId: openProduct.id, byVariant });
    }, () => live && setOpenSerials({ productId: openProduct.id, byVariant: {} }));
    return () => { live = false; };
  }, [openProduct, serialsVersion]);
  const serialsLoaded = openSerials.productId === openProduct?.id;
  const serialsFor = (code) => (serialsLoaded ? openSerials.byVariant[code] || [] : null);
  const [stockPoints, setStockPoints] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [printing, setPrinting] = useState(null); // { product, variant }
  const [flash, setFlash] = useState("");
  const [searching, setSearching] = useState(false);
  // Each search gets a number; only the newest one may update the list, so
  // a slow response for "del" can't overwrite the results for "dell".
  const loadSeq = useRef(0);

  const load = (q) => {
    const seq = ++loadSeq.current;
    setSearching(true);
    api.getAll(`/products/${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then((list) => {
        if (seq === loadSeq.current) setProducts(list);
      })
      .catch((e) => {
        if (seq === loadSeq.current) setError(e.message);
      })
      .finally(() => {
        if (seq === loadSeq.current) setSearching(false);
      });
  };

  useEffect(() => {
    api.get("/stock-points/?active=1").then((d) => setStockPoints(d.results ?? d)).catch(() => {});
  }, []);

  // a store was renamed / edited: refresh the store list and the stock rows' store names
  useEffect(() => onStoreChanged(() => {
    api.get("/stock-points/?active=1").then((d) => setStockPoints(d.results ?? d)).catch(() => {});
    load(query);
  }), [query]);

  // Also does the first load (query ""), immediately rather than after the
  // typing pause -- previously a separate mount effect loaded it twice.
  useEffect(() => {
    const t = setTimeout(() => load(query), query ? 300 : 0);
    return () => clearTimeout(t);
  }, [query]);

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!products) return <Spinner label="Loading inventory…" />;

  const onScanFound = (product) => {
    setScanning(false);
    setOpenProduct(product);
  };

  const onStockAdded = (result) => {
    setAdding(false);
    load(query);
    setOpenProduct(result.product);
    const bits = [];
    if (result.generated_product_code) bits.push(`product code ${result.product.product_code} auto-generated`);
    if (result.generated_variant_code) bits.push(`${result.created_variant ? "new variant" : "variant code"} ${result.variant.code}${result.variant.colour ? ` (${result.variant.colour})` : ""} auto-generated`);
    if (result.serials?.length) {
      const list = result.serials;
      bits.push(`serial number${list.length > 1 ? "s" : ""} ${list.length > 3 ? `${list.slice(0, 3).join(", ")} and ${list.length - 3} more` : list.join(", ")} generated`);
    }
    const level = result.previous_quantity !== undefined ? ` Stock there: ${result.previous_quantity} → ${result.new_quantity}.` : ` Stock there: ${result.new_quantity}.`;
    setFlash(`Added stock at ${result.stock_point}${result.location ? ` (${result.location})` : ""}.${level}${bits.length ? " " + bits.join(", ") + "." : ""}`);
    setTimeout(() => setFlash(""), 6000);
  };

  // Patch one stock row in both the open detail panel and the list,
  // so the new location shows everywhere without refetching.
  const onLocationSaved = (updated) => {
    const patch = (p) => ({
      ...p,
      variants: p.variants.map((v) => ({ ...v, stock: v.stock.map((s) => (s.id === updated.id ? updated : s)) })),
    });
    setOpenProduct((p) => (p ? patch(p) : p));
    setProducts((list) => list.map((p) => (p.id === openProduct?.id ? patch(p) : p)));
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="px-[1rem] pt-[1.5rem] sm:px-[2rem]">
        <PageHeader title="Inventory" subtitle="Stock levels and product records across every shop and online channel" />
      </div>
      <header className="flex flex-wrap items-center gap-3 px-[1rem] py-[1rem] sm:px-[2rem]">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by product, brand, product ID, or variant code"
          className="basis-full sm:basis-0"
        />
        <div className="flex flex-1 items-center gap-2 sm:flex-none">
          <PillButton icon={ScanBarcode} onClick={() => setScanning(true)} className="flex-1 justify-center sm:flex-none">Scan</PillButton>
          <PillButton icon={ScanLine} onClick={() => setTracing("")} className="flex-1 justify-center sm:flex-none">Trace serial</PillButton>
          {can("inventory.edit") && (
            <PillButton icon={Plus} primary onClick={() => setAdding(true)} className="flex-1 justify-center sm:flex-none">Add stock</PillButton>
          )}
        </div>
        <p className="basis-full text-xs" aria-live="polite" style={{ fontFamily: F.body, color: C.inkSoft }}>
          {searching ? "Searching…" : `${products.length} product${products.length === 1 ? "" : "s"}${query ? ` matching “${query}”` : ""}`}
        </p>
      </header>

      {flash && (
        <div role="status" className="mx-[1rem] mb-1 flex items-center gap-2 rounded-xl px-3 py-2 sm:mx-[2rem]" style={{ backgroundColor: `color-mix(in srgb, ${C.green} 8%, transparent)`, border: `1px solid color-mix(in srgb, ${C.green} 33%, transparent)` }}>
          <Check size={13} style={{ color: C.green }} />
          <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{flash}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-[1rem] pb-6 pt-1 sm:px-[2rem]">
        <div className="hidden grid-cols-[2fr_1fr_1fr_1fr_1fr_1.8fr] gap-3 px-5 pb-2 text-xs uppercase md:grid" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: C.inkSoft }}>
          <span>Product</span><span>Product ID · HSN</span><span>Processor</span><span>Sell price</span><span>Shared stock</span><span>Stock location</span>
        </div>
        <div className="flex flex-col gap-2.5">
          {products.map((p) => {
            const totalStock = p.variants.reduce((a, v) => a + v.total_stock, 0);
            const lowest = p.variants.some((v) => v.total_stock <= 4);
            return (
              <button
                key={p.id}
                onClick={() => setOpenProduct(p)}
                data-listcard
                data-selected={openProduct?.id === p.id}
                className="grid w-full grid-cols-2 gap-x-4 gap-y-3 px-4 py-3.5 text-left sm:px-5 md:grid-cols-[2fr_1fr_1fr_1fr_1fr_1.8fr] md:items-center md:gap-3"
              >
                <div className="col-span-2 flex min-w-0 items-start justify-between gap-3 md:col-span-1 md:block">
                  <div className="min-w-0">
                    <p className="truncate text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{p.display_name}</p>
                    <p className="mt-0.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.condition} · {p.variants.length ? `${p.variants.length} variant${p.variants.length > 1 ? "s" : ""}` : "no variants"}</p>
                  </div>
                  <span className="shrink-0 md:hidden"><Pill color={lowest ? C.carbon : C.green}>{totalStock} units</Pill></span>
                </div>
                <span className="min-w-0 text-xs" style={{ fontFamily: F.mono, color: C.ink }}>
                  <MobileLabel>Product ID · HSN</MobileLabel>
                  <span className="block truncate" title="Product ID — the same for every unit of this product">{p.product_code}</span>
                  <span className="block break-words" style={{ color: p.hsn ? C.inkSoft : C.amber }}>{p.hsn ? `HSN ${p.hsn}` : "No HSN code"}</span>
                </span>
                <span className="min-w-0 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  <MobileLabel>Processor</MobileLabel>
                  <span className="block truncate">{p.processor || "—"}</span>
                </span>
                <span className="min-w-0 text-sm" style={{ fontFamily: F.mono, color: C.ink }}>
                  <MobileLabel>Sell price</MobileLabel>
                  {p.variants.length ? money(p.variants[0].sell_price) : "—"}
                </span>
                <span className="hidden md:block"><Pill color={lowest ? C.carbon : C.green}>{totalStock} units</Pill></span>
                <span className="block min-w-0">
                  <MobileLabel>Stock location</MobileLabel>
                  <StockLocationCell product={p} />
                </span>
              </button>
            );
          })}
          {!products.length && (
            <div className="flex flex-col items-center gap-2 rounded-2xl px-4 py-12 text-center" style={{ border: `1px dashed ${C.ruleStrong}`, backgroundColor: `color-mix(in srgb, ${C.slip} 60%, transparent)` }}>
              <Search size={22} style={{ color: C.inkSoft }} />
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>No products match that search</p>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Try a brand, model, product ID or variant code.</p>
            </div>
          )}
        </div>
      </div>

      {openProduct && (
        <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={() => setOpenProduct(null)}>
          <div role="dialog" aria-modal="true" aria-label={openProduct.display_name} className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl p-[1.25rem] sm:rounded-2xl sm:p-[1.5rem]" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 18, color: C.ink }}>{openProduct.display_name}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3" style={{ fontFamily: F.body }}>
                  <div><dt style={{ color: C.inkSoft }}>Product ID</dt><dd style={{ fontFamily: F.mono, color: C.ink }}>{openProduct.product_code}</dd></div>
                  <div><dt style={{ color: C.inkSoft }}>HSN code</dt><dd style={{ fontFamily: F.mono, color: openProduct.hsn ? C.ink : C.amber }}>{openProduct.hsn || "Not specified"}</dd></div>
                  <div><dt style={{ color: C.inkSoft }}>Condition</dt><dd style={{ color: C.ink }}>{openProduct.condition}</dd></div>
                </dl>
              </div>
              <button type="button" onClick={() => setOpenProduct(null)} aria-label="Close product details" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
            </div>

            <div className="mt-6 space-y-4">
              {!openProduct.variants.length && (
                <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  No stock recorded yet. Use Add stock → Restock existing item to add units — no variant needed.
                </p>
              )}
              {openProduct.variants.map((v) => (
                <div key={v.code} data-panel style={{ border: `1px solid ${C.rule}` }} className="p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{v.spec}</p>
                      <p className="text-xs" style={{ fontFamily: F.mono, color: C.stamp }} title="Variant SKU">SKU {v.code}{v.colour ? <span style={{ color: C.inkSoft }}> · {v.colour}</span> : null}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(v.sell_price)} <span style={{ color: C.inkSoft, textDecoration: "line-through" }}>{money(v.mrp)}</span></span>
                      <button onClick={() => setPrinting({ product: openProduct, variant: v })} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
                        <Printer size={12} /> Label
                      </button>
                    </div>
                  </div>
                  {(openProduct.serial_tracking || serialsFor(v.code)?.length > 0) && (
                    <UnitList serials={serialsFor(v.code)} productCode={openProduct.product_code} hsn={openProduct.hsn}
                      inStock={v.stock.reduce((n, st) => n + st.quantity, 0)} product={openProduct} variant={v}
                      canEdit={can("inventory.edit")} onChanged={() => { setSerialsVersion((n) => n + 1); load(query); }} onTrace={(sn) => setTracing(sn)} />
                  )}
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    {v.stock.map((s) => (
                      <StockTile key={s.id ?? s.stock_point} stock={s} canEdit={can("inventory.edit")} onSaved={onLocationSaved} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {scanning && <ScanModal onClose={() => setScanning(false)} onFound={onScanFound} />}
      {adding && <AddStockModal stockPoints={stockPoints} onClose={() => setAdding(false)} onAdded={onStockAdded} />}
      {tracing !== null && <TraceSerialModal key={tracing} initial={tracing} onClose={() => setTracing(null)} />}
      {printing && <PrintModal product={printing.product} variant={printing.variant} onClose={() => setPrinting(null)} />}
    </div>
  );
}
