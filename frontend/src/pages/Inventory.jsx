import { useEffect, useState } from "react";
import {
  AlertTriangle, Check, Loader2, MapPin, Pencil, Plus, Printer, ScanBarcode, X,
} from "lucide-react";
import { C, F, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, PillButton, SearchInput, Spinner } from "../components/Atoms";
import PageHeader from "../components/PageHeader";

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
    <div className="px-2 py-1.5" style={{ backgroundColor: C.slip2 }}>
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
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
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
 *  Add stock -- restock an existing SKU, or bring a brand-new item
 *  into the catalogue. Either product code or variant code is
 *  auto-generated server-side if left blank (the "no HSN yet" case).
 * ------------------------------------------------------------------ */
function AddStockModal({ stockPoints, onClose, onAdded }) {
  const [mode, setMode] = useState("existing"); // existing | new
  const [allProducts, setAllProducts] = useState(null);
  const [productId, setProductId] = useState("");
  const [variantId, setVariantId] = useState("");

  const [brand, setBrand] = useState("");
  const [modelName, setModelName] = useState("");
  const [processor, setProcessor] = useState("");
  const [hsn, setHsn] = useState("");
  const [condition, setCondition] = useState("New");
  const [spec, setSpec] = useState("");
  const [sellPrice, setSellPrice] = useState("");
  const [mrp, setMrp] = useState("");

  const [stockPointId, setStockPointId] = useState(stockPoints[0]?.id || "");
  const [quantity, setQuantity] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode === "existing" && !allProducts) {
      api.getAll("/products/").then(setAllProducts).catch((e) => setError(e.message));
    }
  }, [mode, allProducts]);

  const product = allProducts?.find((p) => p.id === +productId);

  const submit = async () => {
    setError("");
    const qty = +quantity;
    if (!qty || qty <= 0) return setError("Enter a quantity greater than 0.");
    if (!stockPointId) return setError("Pick a shop or channel.");

    let payload = { stock_point: stockPointId, quantity: qty, location: location.trim() };
    if (mode === "existing") {
      if (!productId) return setError("Pick a product.");
      if (product?.variants.length > 1 && !variantId) return setError("This product has several variants — pick one.");
      payload = { ...payload, product: +productId };
      if (variantId) payload.variant = +variantId;
      // No variants yet: the server files the stock under a default
      // "Standard" variant, priced with whatever was entered here.
      if (!product?.variants.length && sellPrice) payload = { ...payload, sell_price: +sellPrice, mrp: mrp ? +mrp : undefined };
    } else {
      if (!modelName.trim()) return setError("Model name is required.");
      if (!sellPrice || +sellPrice <= 0) return setError("Enter a selling price.");
      payload = {
        ...payload, brand: brand.trim(), model_name: modelName.trim(), processor: processor.trim(),
        hsn: hsn.trim(), condition, spec: spec.trim(), sell_price: +sellPrice, mrp: mrp ? +mrp : undefined,
      };
    }

    setBusy(true);
    try {
      const result = await api.post("/inventory/add-stock/", payload);
      onAdded(result);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>Add stock</Eyebrow>
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-4 flex" style={{ border: `1px solid ${C.rule}` }}>
          {[["existing", "Restock existing item"], ["new", "New item"]].map(([k, label]) => (
            <button key={k} onClick={() => setMode(k)} className="flex-1 py-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: mode === k ? C.onAccent : C.inkSoft, backgroundColor: mode === k ? C.stamp : "transparent" }}>{label}</button>
          ))}
        </div>

        {mode === "existing" ? (
          <div className="mt-4 space-y-3">
            {!allProducts ? <Spinner label="Loading catalogue…" /> : (
              <>
                <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Product
                  <select value={productId} onChange={(e) => { const p = allProducts.find((x) => x.id === +e.target.value); setProductId(e.target.value); setVariantId(p?.variants.length === 1 ? String(p.variants[0].id) : ""); }} className="mt-1 w-full py-2 text-sm outline-none" style={{ fontFamily: F.body, background:C.slip, color: C.ink, border: `1px solid ${C.rule}` }}>
                    <option value="">Select a product…</option>
                    {allProducts.map((p) => <option key={p.id} value={p.id}>{p.display_name} · {p.product_code}</option>)}
                  </select>
                </label>
                {product && product.variants.length > 0 && (
                  <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Variant{product.variants.length === 1 ? " (only one)" : ""}
                    <select value={variantId} onChange={(e) => setVariantId(e.target.value)} className="mt-1 w-full py-2 text-sm outline-none" style={{ fontFamily: F.body, background: C.slip, color: C.ink, border: `1px solid ${C.rule}` }}>
                      {product.variants.length > 1 && <option value="">Select a variant…</option>}
                      {product.variants.map((v) => <option key={v.id} value={v.id}>{v.spec} · {v.code} · {v.total_stock} in stock</option>)}
                    </select>
                  </label>
                )}
                {product && product.variants.length === 0 && (
                  <div className="space-y-3">
                    <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                      This product has no variants — the stock will be added to the product directly.
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Sell price (₹, optional)
                        <input value={sellPrice} onChange={(e) => setSellPrice(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
                      </label>
                      <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>MRP (₹, optional)
                        <input value={mrp} onChange={(e) => setMrp(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
                      </label>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Brand
                <input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="Leave blank for accessories" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Model name
                <input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="e.g. Latitude 5440" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Processor
                <input value={processor} onChange={(e) => setProcessor(e.target.value)} placeholder="Optional" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Condition
                <select value={condition} onChange={(e) => setCondition(e.target.value)} className="mt-1 w-full py-2 text-sm outline-none" style={{ fontFamily: F.body, background: C.slip, color: C.ink, border: `1px solid ${C.rule}` }}>
                  <option>New</option><option>Refurbished</option>
                </select>
              </label>
              <label className="block text-xs sm:col-span-2" style={{ fontFamily: F.body, color: C.inkSoft }}>HSN code
                <input value={hsn} onChange={(e) => setHsn(e.target.value)} placeholder="Leave blank if none applies -- a code will be generated" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
                {!hsn.trim() && <span className="mt-1 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, color: C.amber }}><AlertTriangle size={11} />No HSN — an internal code will be auto-generated for this item.</span>}
              </label>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="block text-xs sm:col-span-1" style={{ fontFamily: F.body, color: C.inkSoft }}>Variant / spec (optional)
                <input value={spec} onChange={(e) => setSpec(e.target.value)} placeholder="e.g. 8GB / 256GB SSD" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Sell price (₹)
                <input value={sellPrice} onChange={(e) => setSellPrice(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
              <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>MRP (₹, optional)
                <input value={mrp} onChange={(e) => setMrp(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
              </label>
            </div>
          </div>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Shop / channel
            <select value={stockPointId} onChange={(e) => setStockPointId(e.target.value)} className="mt-1 w-full py-2 text-sm outline-none" style={{ fontFamily: F.body, background: C.slip, color: C.ink, border: `1px solid ${C.rule}` }}>
              {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Quantity received
            <input value={quantity} onChange={(e) => setQuantity(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
          </label>
        </div>
        <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Placed at (rack / shelf, optional)
          <input value={location} maxLength={80} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Rack A / Shelf 3 — leave blank to keep the current spot" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <Plus size={13} /> {busy ? "Adding…" : "Add stock"}
        </button>
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
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>Label printer</Eyebrow>
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>

        <div id="print-label-area" className="mt-4 p-3" data-panel style={{ border: "1px dashed #B9C2CE", backgroundColor: "#F2F0EA" }}>
          <p className="text-xs" style={{ fontFamily: F.mono, color: "#5B5F52" }}>Vantage Computers</p>
          <p className="mt-1 text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: "#171634" }}>{product.display_name}</p>
          <p className="text-xs" style={{ fontFamily: F.body, color: "#5B5F52" }}>{variant.spec}</p>
          <div className="mt-2 flex h-10 items-center justify-center" style={{ background: "repeating-linear-gradient(90deg, #171634 0 2px, transparent 2px 5px)" }} />
          <p className="mt-1 text-center text-xs" style={{ fontFamily: F.mono, color: "#171634" }}>{variant.code}</p>
          <p className="text-center text-xs" style={{ fontFamily: F.mono, color: "#5B5F52" }}>{product.hsn ? `HSN ${product.hsn}` : "Internal code — no HSN"} · {money(variant.sell_price)}</p>
        </div>

        <button onClick={() => window.print()} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
          <Printer size={13} /> Print sticker
        </button>
        <p className="mt-2 text-center text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Choose your magnetic/thermal label printer in the print dialog that opens.</p>
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
  const [stockPoints, setStockPoints] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [printing, setPrinting] = useState(null); // { product, variant }
  const [flash, setFlash] = useState("");

  const load = (q) => {
    api.getAll(`/products/${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then(setProducts)
      .catch((e) => setError(e.message));
  };

  useEffect(() => {
    load("");
    api.get("/stock-points/").then((d) => setStockPoints(d.results ?? d));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(query), 300);
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
    if (result.generated_variant_code) bits.push(`variant code ${result.variant.code} auto-generated`);
    setFlash(`Added stock at ${result.stock_point}${result.location ? ` (${result.location})` : ""}.${bits.length ? " " + bits.join(", ") + "." : ""}`);
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
      <div className="px-5 pt-6 sm:px-8">
        <PageHeader title="Inventory" subtitle="Stock levels and product records across every shop and online channel" />
      </div>
      <header className="flex flex-wrap items-center gap-3 px-5 py-4 sm:px-8">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by product, brand, product ID, or variant code" />
        <PillButton icon={ScanBarcode} onClick={() => setScanning(true)}>Scan</PillButton>
        {can("inventory.edit") && (
          <PillButton icon={Plus} primary onClick={() => setAdding(true)}>Add stock</PillButton>
        )}
      </header>

      {flash && (
        <div className="mx-5 mt-3 flex items-center gap-2 px-3 py-2 sm:mx-8" style={{ backgroundColor: `${C.green}14`, border: `1px solid ${C.green}` }}>
          <Check size={13} style={{ color: C.green }} />
          <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{flash}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-5 py-4 sm:px-8">
        <div className="hidden grid-cols-[2fr_1fr_1fr_1fr_1fr_1.8fr] gap-3 px-5 pb-2 text-xs uppercase md:grid" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: C.inkSoft }}>
          <span>Product</span><span>ID / HSN</span><span>Processor</span><span>Sell price</span><span>Shared stock</span><span>Stock location</span>
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
                className="block w-full px-5 py-3.5 text-left md:grid md:grid-cols-[2fr_1fr_1fr_1fr_1fr_1.8fr] md:items-center md:gap-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{p.display_name}</p>
                  <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.condition} · {p.variants.length ? `${p.variants.length} variant${p.variants.length > 1 ? "s" : ""}` : "no variants"}</p>
                </div>
                <span className="text-xs" style={{ fontFamily: F.mono, color: C.ink }}>{p.product_code}<br /><span style={{ color: p.hsn ? C.inkSoft : C.amber }}>{p.hsn ? `HSN ${p.hsn}` : "generated — no HSN"}</span></span>
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{p.processor || "—"}</span>
                <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{p.variants.length ? money(p.variants[0].sell_price) : "—"}</span>
                <span><Pill color={lowest ? C.carbon : C.green}>{totalStock} units</Pill></span>
                <span className="mt-2 block min-w-0 md:mt-0"><StockLocationCell product={p} /></span>
              </button>
            );
          })}
          {!products.length && <p className="px-3 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No products match that search.</p>}
        </div>
      </div>

      {openProduct && (
        <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={() => setOpenProduct(null)}>
          <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <div>
                <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 18, color: C.ink }}>{openProduct.display_name}</p>
                <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{openProduct.product_code} · {openProduct.hsn ? `HSN ${openProduct.hsn}` : "internal code — no matching HSN"} · {openProduct.condition}</p>
              </div>
              <button onClick={() => setOpenProduct(null)}><X size={18} style={{ color: C.inkSoft }} /></button>
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
                      <p className="text-xs" style={{ fontFamily: F.mono, color: C.stamp }}>{v.code}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(v.sell_price)} <span style={{ color: C.inkSoft, textDecoration: "line-through" }}>{money(v.mrp)}</span></span>
                      <button onClick={() => setPrinting({ product: openProduct, variant: v })} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
                        <Printer size={12} /> Label
                      </button>
                    </div>
                  </div>
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
      {printing && <PrintModal product={printing.product} variant={printing.variant} onClose={() => setPrinting(null)} />}
    </div>
  );
}
