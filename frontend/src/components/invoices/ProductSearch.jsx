import { useEffect, useMemo, useRef, useState } from "react";
import { Hash, Search, ScanLine, Tag } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

const norm = (s) => String(s || "").toLowerCase();

/*
 * The product box on a sale line: type a serial number, a product ID
 * (VC-LAP-0001), a SKU (VC-SKU-0001) or the name. A serial number picks the
 * exact unit on this shop's shelf; a SKU picks that variant.
 * onPick({ productId, variantId?, serial? })
 */
export default function ProductSearch({ products, productId, stockPointId, onPick }) {
  const selected = products.find((p) => p.id === +productId);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [units, setUnits] = useState([]);
  const [active, setActive] = useState(0);
  const box = useRef(null);

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  // serial numbers live on the server (only units on this shop's shelf)
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3 || !stockPointId) { setUnits([]); return undefined; }
    const timer = setTimeout(() => {
      api.get(`/stock-serials/find/?q=${encodeURIComponent(q)}&stock_point=${stockPointId}`).then(setUnits, () => setUnits([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, stockPointId]);

  const matches = useMemo(() => {
    const q = norm(query.trim());
    if (!q) return products.slice(0, 30).map((p) => ({ kind: "product", product: p }));
    const out = [];
    for (const p of products) {
      const sku = p.variants.find((v) => norm(v.code).includes(q));
      if (norm(p.product_code).includes(q)) out.push({ kind: "code", product: p });
      else if (sku) out.push({ kind: "sku", product: p, variant: sku });
      else if (norm(`${p.display_name} ${p.brand || ""}`).includes(q) || q.split(/\s+/).every((w) => norm(p.display_name).includes(w))) {
        out.push({ kind: "product", product: p });
      }
      if (out.length >= 30) break;
    }
    return out;
  }, [products, query]);

  const options = [
    ...units.map((u) => ({ kind: "serial", unit: u, product: products.find((p) => p.id === u.product) })).filter((o) => o.product),
    ...matches,
  ];

  const choose = (o) => {
    if (o.kind === "serial") onPick({ productId: String(o.product.id), variantId: String(o.unit.variant), serial: o.unit.serial_number });
    else if (o.kind === "sku") onPick({ productId: String(o.product.id), variantId: String(o.variant.id) });
    else onPick({ productId: String(o.product.id) });
    setQuery("");
    setOpen(false);
  };

  const onKey = (e) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) { setOpen(true); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (options[active]) choose(options[active]); }
    else if (e.key === "Escape") setOpen(false);
  };

  const ICON = { serial: ScanLine, sku: Tag, code: Hash, product: Search };
  const HINT = { serial: "Serial no.", sku: "SKU", code: "Product ID" };

  return (
    <div ref={box} className="relative col-span-4 min-w-0 sm:col-span-1">
      {/* one box: the input inside stays bare (no second border); the box lights up while searching */}
      <div className="flex items-center gap-1.5 rounded-md px-2" style={{ border: `1px solid ${open ? C.stamp : C.rule}`, background: C.slip }}>
        <Search size={13} style={{ color: C.inkSoft, flexShrink: 0 }} />
        <input
          value={open ? query : (selected?.display_name || query)}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => { setOpen(true); setQuery(""); setActive(0); }}
          onKeyDown={onKey}
          placeholder={selected ? selected.display_name : "Search by serial no., product ID or name"}
          title={selected?.display_name || "Search by serial no., product ID (VC-LAP-…), SKU or name"}
          aria-label="Product"
          role="combobox"
          aria-expanded={open}
          data-bare
          className="w-full min-w-0 truncate bg-transparent py-1.5 text-sm outline-none"
          style={{ fontFamily: F.body, color: C.ink }}
        />
      </div>
      {open && (
        <ul role="listbox" className="absolute left-0 right-0 z-40 mt-1 max-h-64 overflow-y-auto shadow-lg sm:min-w-[22rem]" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
          {options.length === 0 && (
            <li className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
              {query.trim().length < 3 ? "No product matches. Serial numbers are searched from 3 characters." : `Nothing in stock here matches “${query.trim()}”.`}
            </li>
          )}
          {options.map((o, n) => {
            const Icon = ICON[o.kind];
            return (
              <li key={`${o.kind}-${o.unit?.serial_number || o.variant?.id || o.product.id}`} role="option" aria-selected={n === active}
                onMouseDown={(e) => { e.preventDefault(); choose(o); }} onMouseEnter={() => setActive(n)}
                className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm"
                style={{ backgroundColor: n === active ? C.slip2 : "transparent", fontFamily: F.body, color: C.ink }}>
                <Icon size={12} style={{ color: o.kind === "product" ? C.inkSoft : C.stamp, flexShrink: 0 }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{o.kind === "serial" ? o.unit.label : o.product.display_name}{o.kind === "sku" ? ` (${o.variant.spec})` : ""}</span>
                  <span className="block truncate text-[11px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>
                    {o.kind === "serial" ? `S/N ${o.unit.serial_number}` : o.kind === "sku" ? o.variant.code : o.product.product_code}
                  </span>
                </span>
                {HINT[o.kind] && <span className="shrink-0 text-[10px] uppercase" style={{ fontFamily: F.body, fontWeight: 700, color: C.stamp }}>{HINT[o.kind]}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
