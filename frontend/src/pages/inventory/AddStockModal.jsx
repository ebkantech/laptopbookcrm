import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Boxes, CircleHelp, HardDrive, Headphones, Laptop, MemoryStick, Package, PackageCheck, PackagePlus, Plug, Plus,
  Save, Search, Store,
} from "lucide-react";
import { api } from "../../lib/api";
import { money } from "../../lib/theme";
import { Alert, Dialog, Field } from "../settings/StaffUi";
import "../settings/staff.css";
import "./addStock.css";

/*
 * Inventory -> Add stock. One modal, two entry types, both through the
 * existing POST /inventory/add-stock/ (catalog.views.AddStockView, which
 * checks inventory.edit, the account's store and inactive stores; the
 * rules themselves are in catalog.new_product and are checked there again):
 *   New product      -> { category, brand, model_name, description, colour, hsn, specs,
 *                         stock_point, quantity, sell_price, mrp, location }
 *   Existing product -> { entry: "existing", product, variant | new_variant + spec,
 *                         colour, hsn?, stock_point, quantity, sell_price?, mrp?, location }
 * Serial numbers are never typed: the server generates one per unit.
 * Colour is a Variant field, always typed in: a product received in a new
 * colour becomes a new variant of that product, never a relabelled old one.
 */

const CATEGORIES = [
  { id: "laptop", label: "Laptop", icon: Laptop },
  { id: "charger", label: "Charger", icon: Plug },
  { id: "ssd", label: "SSD", icon: HardDrive },
  { id: "ram", label: "RAM", icon: MemoryStick },
  { id: "accessories", label: "Accessories", icon: Headphones },
  { id: "other", label: "Other", icon: Package },
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.label]));

// Mirrors catalog.new_product.CATEGORY_FIELDS. `options`: a fixed choice;
// `suggest`: common values offered while typing, any text allowed.
const SPEC_FIELDS = {
  laptop: [
    { key: "processor", label: "Processor", required: true, placeholder: "e.g. Intel Core i5-1235U" },
    { key: "generation", label: "Generation", placeholder: "e.g. 12th Gen" },
    { key: "ram", label: "RAM", required: true, suggest: ["4GB", "8GB", "16GB", "32GB"] },
    { key: "storage", label: "Storage", required: true, placeholder: "e.g. 512GB SSD" },
    { key: "screen_size", label: "Screen size", suggest: ['13.3"', '14"', '15.6"', '16"'] },
  ],
  charger: [
    { key: "wattage", label: "Wattage", required: true, suggest: ["45W", "65W", "90W", "130W"] },
    { key: "connector_type", label: "Connector type", required: true, suggest: ["USB-C", "Barrel 4.5mm", "Barrel 7.4mm", "MagSafe"] },
    { key: "output_voltage", label: "Output voltage", placeholder: "e.g. 19.5V" },
    { key: "compatibility", label: "Compatibility", placeholder: "e.g. Dell Latitude, Inspiron", wide: true },
  ],
  ssd: [
    { key: "capacity", label: "Capacity", required: true, suggest: ["256GB", "512GB", "1TB", "2TB"] },
    { key: "interface", label: "Interface", required: true, options: ["SATA", "NVMe"] },
    { key: "form_factor", label: "Form factor", suggest: ['2.5"', "M.2 2280", "M.2 2242"] },
  ],
  ram: [
    { key: "capacity", label: "Capacity", required: true, suggest: ["4GB", "8GB", "16GB", "32GB"] },
    { key: "ddr_type", label: "DDR type", required: true, suggest: ["DDR3", "DDR3L", "DDR4", "DDR5"] },
    { key: "speed", label: "Speed", suggest: ["2400MHz", "2666MHz", "3200MHz", "4800MHz"] },
    { key: "form_factor", label: "Form factor", suggest: ["SO-DIMM", "DIMM"] },
  ],
  accessories: [
    { key: "accessory_type", label: "Accessory type", required: true, suggest: ["Mouse", "Keyboard", "Bag", "Headphones", "Cable", "Adapter"] },
    { key: "warranty", label: "Warranty", placeholder: "e.g. 6 months" },
    { key: "other_specs", label: "Other specifications", textarea: true, wide: true },
  ],
  other: [
    { key: "variant_size", label: "Variant / size" },
    { key: "unit", label: "Unit", required: true, suggest: ["Piece", "Box", "Pack", "Set", "Metre"] },
    { key: "custom_specs", label: "Custom specifications", textarea: true, wide: true },
  ],
};
const NAME_LABEL = { accessories: "Product name", other: "Product name" };
const BRAND_OPTIONAL = new Set(["other"]);
const NOT_SPECIFIED = "Not specified";

const digits = (v) => v.replace(/\D/g, "").slice(0, 9);
const same = (a, b) => (a || "").trim().toLowerCase() === (b || "").trim().toLowerCase();
const tidyColour = (v) => v.replace(/\s+/g, " ").trim();

function errorsFrom(err) {
  const out = {};
  const body = err?.body && typeof err.body === "object" ? err.body : {};
  for (const [k, v] of Object.entries(body)) {
    if (k === "code") continue;
    out[k] = Array.isArray(v) ? v.filter((m) => typeof m === "string").join(" ") : typeof v === "string" ? v : "";
  }
  if (err?.status === 403) out.detail = "Your role can't add stock, or this isn't your store.";
  else if (err?.status === 404) out.detail = "That store isn't available to your account.";
  if (!Object.values(out).some(Boolean)) out.detail = err?.message || "The stock couldn't be saved.";
  return out;
}

/* A labelled control; `children(id, error)` renders the input. */
function F({ label, required, error, hint, wide, children }) {
  const id = useId();
  return (
    <div className={wide ? "as-wide" : undefined}>
      <Field id={id} label={<>{label}{required && <span className="as-req" aria-hidden="true"> *</span>}</>} error={error} hint={hint}>
        {children(id, error)}
      </Field>
    </div>
  );
}

function SpecInput({ field, value, onChange, error, id }) {
  if (field.options) {
    return (
      <div className="as-choice" role="radiogroup" aria-label={field.label} id={id}>
        {field.options.map((o) => <button key={o} type="button" role="radio" aria-checked={value === o} onClick={() => onChange(o)}>{o}</button>)}
      </div>
    );
  }
  if (field.textarea) return <textarea id={id} className="st-input as-textarea" value={value} maxLength={120} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} />;
  return (
    <>
      <input id={id} className="st-input" value={value} maxLength={120} placeholder={field.placeholder} list={field.suggest ? `${id}-list` : undefined}
        onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} aria-required={field.required || undefined} />
      {field.suggest && <datalist id={`${id}-list`}>{field.suggest.map((s) => <option key={s} value={s} />)}</datalist>}
    </>
  );
}

function ColourInput({ value, onChange, error, hint, label = "Colour" }) {
  // always a plain text box -- any colour can be typed, nothing to pick from
  return (
    <F label={label} error={error} hint={hint}>
      {(id, err) => <input id={id} className="st-input" type="text" value={value} maxLength={40} autoComplete="off" spellCheck={false}
        onChange={(e) => onChange(e.target.value)} placeholder="e.g. Black, Silver, Space Grey" aria-invalid={!!err} />}
    </F>
  );
}

/* ---------------------------------------------------------------- *
 * Serial numbers & HSN (both flows)
 * ---------------------------------------------------------------- */

// Mirrors catalog.new_product.serial_prefix -- the server makes the serials.
const serialPrefix = (name) => {
  const letters = (name || "").match(/[A-Za-z]/g) || [];
  return letters.length >= 2 ? letters.slice(0, 2).join("").toUpperCase() : null;
};

/* No serial inputs: one serial number per unit is generated by the server
   when the stock is saved -- two letters of the product name + 5 digits. */
function SerialNote({ name, quantity }) {
  const prefix = serialPrefix(name);
  return (
    <div className="as-serial-note as-wide" role="note">
      <p className="st-label">Serial numbers</p>
      {prefix ? (
        <p>{quantity > 0 ? `${quantity} ${quantity === 1 ? "serial number is" : "unique serial numbers are"}` : "One serial number per unit is"} generated automatically when you save —
          {" "}<b className="as-mono">{prefix}</b> + 5 random digits, e.g. <b className="as-mono">{prefix}58321</b>.</p>
      ) : (
        <p>Generated automatically when you save, from the first two letters of the product name.</p>
      )}
    </div>
  );
}

const HSN_ERROR = "Enter the HSN code as exactly 10 digits, or leave it empty.";
const hsnInvalid = (v) => !!v && !/^\d{10}$/.test(v);

function HsnInput({ value, onChange, error, hint, placeholder = "e.g. 1234567890" }) {
  return (
    <F label="HSN code" error={error} hint={hint}>
      {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={value} maxLength={10} autoComplete="off"
        onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 10))} aria-invalid={!!err} placeholder={placeholder} />}
    </F>
  );
}

/* ---------------------------------------------------------------- *
 * New product
 * ---------------------------------------------------------------- */

function NewProductForm({ stockPoints, setBusy, onAdded, registerSubmit, scrollTo }) {
  const [category, setCategory] = useState("");
  const [v, setV] = useState({
    brand: "", model_name: "", description: "", colour: "", hsn: "", condition: "New", specs: {},
    stock_point: stockPoints.length === 1 ? String(stockPoints[0].id) : "", quantity: "1", sell_price: "", mrp: "", location: "",
  });
  const [errors, setErrors] = useState({});
  const set = (k) => (val) => { setV((s) => ({ ...s, [k]: val })); setErrors((e) => ({ ...e, [k]: undefined })); };
  // each category keeps its own specifications, so switching back loses nothing
  const setSpec = (key) => (val) => {
    setV((s) => ({ ...s, specs: { ...s.specs, [category]: { ...s.specs[category], [key]: val } } }));
   
    setErrors((e) => ({ ...e, [`specs.${key}`]: undefined }));
  };
  const qty = Number(v.quantity) || 0;

  const check = () => {
    const e = {};
    if (!category) e.category = "Choose a product category.";
    if (category && !BRAND_OPTIONAL.has(category) && !v.brand.trim()) e.brand = "Enter the brand.";
    if (!v.model_name.trim()) e.model_name = `Enter the ${(NAME_LABEL[category] || "model / product name").toLowerCase()}.`;
    for (const f of SPEC_FIELDS[category] || []) {
      if (f.required && !(v.specs[category]?.[f.key] || "").trim()) e[`specs.${f.key}`] = `Enter the ${f.label.toLowerCase()}.`;
    }
    if (hsnInvalid(v.hsn)) e.hsn = HSN_ERROR;
    if (v.model_name.trim() && !serialPrefix(`${v.brand} ${v.model_name}`)) e.model_name = "The product name needs at least two letters (A–Z) to make its serial numbers.";
    if (!v.stock_point) e.stock_point = "Choose the store / stock point.";
    if (!(qty > 0)) e.quantity = "Enter a quantity of at least 1.";
    if (!(Number(v.sell_price) > 0)) e.sell_price = "Enter the selling price.";
    if (v.mrp && Number(v.mrp) < Number(v.sell_price)) e.mrp = "MRP can't be lower than the selling price.";
    return e;
  };

  const submit = async () => {
    const found = check();
    setErrors(found);
    if (Object.keys(found).length) return scrollTo();
    const specs = Object.fromEntries(Object.entries(v.specs[category] || {}).map(([k, x]) => [k, x.trim()]).filter(([, x]) => x));
    setBusy(true);
    try {
      onAdded(await api.post("/inventory/add-stock/", {
        category, brand: v.brand.trim(), model_name: v.model_name.trim(), description: v.description.trim(),
        colour: tidyColour(v.colour), hsn: v.hsn, specs, ...(category === "laptop" ? { condition: v.condition } : {}),
        stock_point: Number(v.stock_point), quantity: qty, sell_price: Number(v.sell_price), mrp: v.mrp ? Number(v.mrp) : null,
        location: v.location.trim(),
      }));
    } catch (err) {
      setErrors(errorsFrom(err));
      scrollTo();
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { registerSubmit(submit); });

  const general = [errors.detail, errors.non_field_errors, errors.specs].filter(Boolean);
  return (
    <div className="as-body">
      {general.length > 0 && <Alert>{general.join(" ")}</Alert>}
      <section className="as-section" aria-labelledby="as-cat-title">
        <h3 id="as-cat-title" className="as-section-title">Product category<span className="as-req" aria-hidden="true"> *</span></h3>
        <div className="as-tiles" role="radiogroup" aria-labelledby="as-cat-title" data-invalid={errors.category ? "" : undefined}>
          {CATEGORIES.map((c) => (
            <button key={c.id} type="button" role="radio" aria-checked={category === c.id} className="as-tile"
              onClick={() => { setCategory(c.id); setErrors((e) => ({ ...e, category: undefined })); }}>
              <c.icon size={22} aria-hidden="true" /><span>{c.label}</span>
            </button>
          ))}
        </div>
        {errors.category && <p className="st-err">{errors.category}</p>}
      </section>

      <div className="as-columns">
        <section className="as-section" aria-labelledby="as-details-title">
          <h3 id="as-details-title" className="as-section-title"><Boxes size={15} aria-hidden="true" />Product details</h3>
          {!category ? (
            <p className="as-empty"><CircleHelp size={16} aria-hidden="true" />Choose a category to see its specifications.</p>
          ) : (
            <div className="as-grid">
              <F label="Brand" required={!BRAND_OPTIONAL.has(category)} error={errors.brand} hint={BRAND_OPTIONAL.has(category) ? "Optional" : undefined}>
                {(id, err) => <input id={id} className="st-input" value={v.brand} maxLength={40} onChange={(e) => set("brand")(e.target.value)} aria-invalid={!!err} placeholder="e.g. Dell" />}
              </F>
              <F label={NAME_LABEL[category] || "Model / product name"} required error={errors.model_name}>
                {(id, err) => <input id={id} className="st-input" value={v.model_name} maxLength={80} onChange={(e) => set("model_name")(e.target.value)} aria-invalid={!!err} placeholder={category === "laptop" ? "e.g. Latitude 5440" : ""} />}
              </F>
              {SPEC_FIELDS[category].map((f) => (
                <F key={`${category}-${f.key}`} label={f.label} required={f.required} error={errors[`specs.${f.key}`]} wide={f.wide}>
                  {(id, err) => <SpecInput field={f} id={id} value={v.specs[category]?.[f.key] || ""} onChange={setSpec(f.key)} error={err} />}
                </F>
              ))}
              {category === "laptop" && (
                <F label="Condition">
                  {(id) => (
                    <select id={id} className="st-input" value={v.condition} onChange={(e) => set("condition")(e.target.value)}>
                      <option>New</option><option>Refurbished</option><option>Used</option>
                    </select>
                  )}
                </F>
              )}
              <ColourInput value={v.colour} onChange={set("colour")} error={errors.colour} />
              <HsnInput value={v.hsn} onChange={set("hsn")} error={errors.hsn}
                hint="Optional · 10 digits, shared by every unit of this product. The Product ID is generated once when you save." />
              <F label="Description" wide error={errors.description}>
                {(id) => <textarea id={id} className="st-input as-textarea" value={v.description} maxLength={2000} onChange={(e) => set("description")(e.target.value)} />}
              </F>
            </div>
          )}
        </section>

        <section className="as-section" aria-labelledby="as-stock-title">
          <h3 id="as-stock-title" className="as-section-title"><Store size={15} aria-hidden="true" />Stock information</h3>
          <div className="as-grid">
            <F label="Store / stock point" required error={errors.stock_point} wide>
              {(id, err) => (
                <select id={id} className="st-input" value={v.stock_point} onChange={(e) => set("stock_point")(e.target.value)} aria-invalid={!!err}>
                  <option value="">Choose…</option>
                  {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              )}
            </F>
            <F label="Quantity" required error={errors.quantity}>
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={v.quantity} onChange={(e) => set("quantity")(digits(e.target.value))} aria-invalid={!!err} />}
            </F>
            <F label="Selling price (₹)" required error={errors.sell_price}>
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={v.sell_price} onChange={(e) => set("sell_price")(digits(e.target.value))} aria-invalid={!!err} placeholder="0" />}
            </F>
            <F label="MRP (₹)" error={errors.mrp} hint="Optional — defaults to the selling price">
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={v.mrp} onChange={(e) => set("mrp")(digits(e.target.value))} aria-invalid={!!err} placeholder="0" />}
            </F>
            <F label="Placed at (rack / shelf)" wide hint="Optional">
              {(id) => <input id={id} className="st-input" value={v.location} maxLength={80} onChange={(e) => set("location")(e.target.value)} placeholder="e.g. Rack A / Shelf 3" />}
            </F>
            <SerialNote name={`${v.brand} ${v.model_name}`} quantity={qty} />
          </div>
          {Number(v.sell_price) > 0 && qty > 0 && <p className="as-total">Stock value at selling price: <b className="as-mono">{money(Number(v.sell_price) * qty)}</b></p>}
        </section>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- *
 * Existing product
 * ---------------------------------------------------------------- */

const colourText = (c) => c || NOT_SPECIFIED;
const stockAt = (variant, slug) => variant?.stock?.find((s) => s.stock_point === slug)?.quantity ?? 0;

function ProductSearch({ onPick }) {
  const [q, setQ] = useState("");
  const [state, setState] = useState({ q: null, rows: null, error: null });
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return undefined;
    let live = true;
    const t = setTimeout(() => {
      api.get(`/products/?q=${encodeURIComponent(term)}`).then(
        (d) => live && setState({ q: term, rows: d.results ?? d, error: null }),
        (error) => live && setState({ q: term, rows: null, error }),
      );
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  const term = q.trim();
  const ready = state.q === term;
  return (
    <div className="as-search">
      <label className="as-search-box">
        <Search size={16} aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} autoFocus placeholder="Search name, brand, model, SKU / product code or serial number"
          aria-label="Search the catalogue" />
      </label>
      {term.length < 2 ? <p className="st-help">Type at least 2 characters.</p>
        : !ready ? <p className="st-help">Searching…</p>
          : state.error ? <Alert>{state.error.message || "The catalogue couldn't be searched."}</Alert>
            : !state.rows.length ? <p className="as-empty"><CircleHelp size={16} aria-hidden="true" />No catalogue product matches “{term}”. Use New product to add it.</p> : (
              <ul className="as-results" aria-label="Matching products">
                {state.rows.slice(0, 25).map((p) => {
                  const colours = [...new Set(p.variants.map((x) => x.colour).filter(Boolean))];
                  const units = p.variants.reduce((s, x) => s + (x.total_stock || 0), 0);
                  return (
                    <li key={p.id}>
                      <button type="button" className="as-result" onClick={() => onPick(p)}>
                        <span className="as-result-main">
                          <b>{p.display_name}</b>
                          <span className="as-result-sub">{CATEGORY_LABEL[p.category] || "Uncategorised"} · {p.brand && p.brand !== "—" ? p.brand : "No brand"} · {p.model_name}</span>
                          <span className="as-result-sub as-mono">{p.product_code} · {p.variants.length} {p.variants.length === 1 ? "variant" : "variants"}</span>
                        </span>
                        <span className="as-result-side">
                          <span>{colours.length ? colours.join(", ") : NOT_SPECIFIED}</span>
                          <span className="as-mono">{units} in stock</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
      {ready && state.rows?.length > 25 && <p className="st-help">Showing the first 25 — type more to narrow it down.</p>}
    </div>
  );
}

function ReadOnlyDetails({ product, onChange }) {
  const fields = SPEC_FIELDS[product.category] || [];
  const specs = product.specs || {};
  const shown = fields.filter((f) => specs[f.key]);
  return (
    <div className="as-readonly">
      <div className="as-readonly-head">
        <div className="min-w-0">
          <p className="as-ro-title">{product.display_name}</p>
          <p className="as-result-sub as-mono">{product.product_code}</p>
        </div>
        <button type="button" className="st-btn" onClick={onChange}>Change product</button>
      </div>
      <dl className="as-kv">
        <div><dt>Product ID</dt><dd className="as-mono">{product.product_code}</dd></div>
        <div><dt>HSN code</dt><dd className="as-mono">{product.hsn ? `HSN ${product.hsn}` : NOT_SPECIFIED}</dd></div>
        <div><dt>Category</dt><dd>{CATEGORY_LABEL[product.category] || "Uncategorised"}</dd></div>
        <div><dt>Brand</dt><dd>{product.brand && product.brand !== "—" ? product.brand : NOT_SPECIFIED}</dd></div>
        <div><dt>Model / product name</dt><dd>{product.model_name}</dd></div>
        {product.condition && <div><dt>Condition</dt><dd>{product.condition}</dd></div>}
        {product.processor && !specs.processor && <div><dt>Processor</dt><dd>{product.processor}</dd></div>}
        {shown.map((f) => <div key={f.key}><dt>{f.label}</dt><dd>{specs[f.key]}</dd></div>)}
        {product.description && <div className="as-wide"><dt>Description</dt><dd>{product.description}</dd></div>}
      </dl>
      <p className="st-help">Catalogue details are read-only here — adding stock never changes them.</p>
    </div>
  );
}

function ExistingProductForm({ stockPoints, setBusy, onAdded, registerSubmit, scrollTo }) {
  const [product, setProduct] = useState(null);
  const [choice, setChoice] = useState(""); // variant id, or "new"
  const [colour, setColour] = useState("");
  const [spec, setSpec] = useState("");
  const [store, setStore] = useState(stockPoints.length === 1 ? String(stockPoints[0].id) : "");
  const [sell, setSell] = useState("");
  const [mrp, setMrp] = useState("");
  const [location, setLocation] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [hsn, setHsn] = useState("");
  const [errors, setErrors] = useState({});
  const clear = (...keys) => setErrors((e) => { const n = { ...e }; keys.forEach((k) => delete n[k]); return n; });

  const variants = useMemo(() => product?.variants || [], [product]);
  const variant = choice && choice !== "new" ? variants.find((x) => String(x.id) === choice) : null;
  const isNew = choice === "new";
  const storeSlug = stockPoints.find((s) => String(s.id) === store)?.slug;
  const qty = Number(quantity) || 0;
  const current = variant && storeSlug ? stockAt(variant, storeSlug) : 0;
  // the variant a typed colour (+ spec) already is -- so it's reused, not duplicated
  const twin = isNew ? variants.find((x) => same(x.spec, spec || "Standard") && same(x.colour, colour)) : null;
  const colourDiffers = variant && colour.trim() && !same(colour, variant.colour);

  const pickVariant = (id, list = variants) => {
    setChoice(id);
    const chosen = list.find((x) => String(x.id) === id);
    if (chosen) { setColour(chosen.colour || ""); setSell(String(chosen.sell_price)); setMrp(String(chosen.mrp)); }
    else { setSell(""); setMrp(""); }
    clear("variant", "colour", "sell_price", "mrp");
  };
  const pickProduct = (p) => {
    setProduct(p);
    setSpec(p.variants[0]?.spec || "");
    setHsn("");
    setErrors({});
   
    if (p.variants.length === 1) pickVariant(String(p.variants[0].id), p.variants);
    else if (!p.variants.length) { setChoice("new"); setColour(""); setSell(""); setMrp(""); }
    else { setChoice(""); setColour(""); }
  };
  // a different colour on a chosen variant becomes a new colour of the same specification
  const typeColour = (value) => {
    setColour(value);
   
    clear("colour", "variant");
    if (variant && value.trim() && !same(value, variant.colour)) { setChoice("new"); setSpec(variant.spec); }
  };

  const check = () => {
    const e = {};
    if (!product) e.product = "Search for and select a catalogue product.";
    if (product && !choice) e.variant = "Choose the variant this stock belongs to, or add a new colour / specification.";
    if (twin) e.variant = `${twin.code} is already ${twin.spec}${twin.colour ? ` in ${twin.colour}` : ""} — select that variant instead.`;
    if (!store) e.stock_point = "Choose the store / stock point.";
    if (!(qty > 0)) e.quantity = "Enter a quantity of at least 1.";
    if (isNew && !(Number(sell) > 0)) e.sell_price = "Enter the selling price for the new variant.";
    if (mrp && sell && Number(mrp) < Number(sell)) e.mrp = "MRP can't be lower than the selling price.";
    if (hsnInvalid(hsn)) e.hsn = HSN_ERROR;
    return e;
  };

  const submit = async () => {
    const found = check();
    setErrors(found);
    if (Object.keys(found).length) return scrollTo();
    // prices are sent only when changed, so a restock never rewrites them by accident
    const priceBody = isNew
      ? { sell_price: Number(sell), mrp: mrp ? Number(mrp) : null }
      : { ...(Number(sell) !== variant.sell_price && sell ? { sell_price: Number(sell) } : {}), ...(Number(mrp) !== variant.mrp && mrp ? { mrp: Number(mrp) } : {}) };
    setBusy(true);
    try {
      onAdded(await api.post("/inventory/add-stock/", {
        entry: "existing", product: product.id, ...(isNew ? { new_variant: true, spec: spec.trim() } : { variant: variant.id }),
        colour: tidyColour(colour), stock_point: Number(store), quantity: qty, ...priceBody, location: location.trim(),
        // blank keeps the product's saved HSN
        ...(hsn ? { hsn } : {}),
      }));
    } catch (err) {
      setErrors(errorsFrom(err));
      scrollTo();
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { registerSubmit(submit); });

  const general = [errors.detail, errors.non_field_errors, errors.product && product ? errors.product : null].filter(Boolean);
  return (
    <div className="as-body">
      {general.length > 0 && <Alert>{general.join(" ")}</Alert>}
      <div className="as-columns">
        <section className="as-section" aria-labelledby="as-ex-details">
          <h3 id="as-ex-details" className="as-section-title"><Boxes size={15} aria-hidden="true" />Product</h3>
          {!product ? (
            <>
              <ProductSearch onPick={pickProduct} />
              {errors.product && <p className="st-err">{errors.product}</p>}
            </>
          ) : (
            <>
              <ReadOnlyDetails product={product} onChange={() => { setProduct(null); setChoice(""); setErrors({}); }} />
              <div className="as-variants" role="radiogroup" aria-label="Variant for this stock">
                <p className="st-label">Variant for this stock<span className="as-req" aria-hidden="true"> *</span></p>
                {variants.map((x) => (
                  <label key={x.id} className="as-variant" data-checked={String(x.id) === choice || undefined}>
                    <input type="radio" name="as-variant" checked={String(x.id) === choice} onChange={() => { pickVariant(String(x.id)); }} />
                    <span className="as-variant-main">
                      <b className="as-mono">{x.code}</b>
                      <span>{x.spec} · {colourText(x.colour)}</span>
                    </span>
                    <span className="as-variant-side">
                      <span className="as-mono">{money(x.sell_price)}</span>
                      <span className="as-result-sub">MRP {money(x.mrp)} · {storeSlug ? `${stockAt(x, storeSlug)} here` : `${x.total_stock} in stock`}</span>
                    </span>
                  </label>
                ))}
                <label className="as-variant" data-checked={isNew || undefined}>
                  <input type="radio" name="as-variant" checked={isNew} onChange={() => { setChoice("new"); setSell(""); setMrp(""); setColour(""); clear("variant"); }} />
                  <span className="as-variant-main"><b><Plus size={13} aria-hidden="true" /> New colour / specification</b>
                    <span>A new variant of this product with its own SKU — existing units are not changed</span></span>
                </label>
                {errors.variant && <p className="st-err">{errors.variant}</p>}
              </div>
            </>
          )}
        </section>

        <section className="as-section" aria-labelledby="as-ex-stock">
          <h3 id="as-ex-stock" className="as-section-title"><Store size={15} aria-hidden="true" />Stock information</h3>
          <div className="as-grid">
            <F label="Store / stock point" required error={errors.stock_point} wide>
              {(id, err) => (
                <select id={id} className="st-input" value={store} onChange={(e) => { setStore(e.target.value); clear("stock_point"); }} aria-invalid={!!err}>
                  <option value="">Choose…</option>
                  {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              )}
            </F>
            <F label="Quantity to add" required error={errors.quantity}>
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={quantity} onChange={(e) => { setQuantity(digits(e.target.value)); clear("quantity"); }} aria-invalid={!!err} />}
            </F>
            <F label="Selling price (₹)" required={isNew} error={errors.sell_price} hint={variant ? `Currently ${money(variant.sell_price)} — change only to update it` : undefined}>
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={sell} onChange={(e) => { setSell(digits(e.target.value)); clear("sell_price", "mrp"); }} aria-invalid={!!err} placeholder="0" />}
            </F>
            <F label="MRP (₹)" error={errors.mrp} hint={variant ? `Currently ${money(variant.mrp)}` : "Optional — defaults to the selling price"}>
              {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={mrp} onChange={(e) => { setMrp(digits(e.target.value)); clear("mrp"); }} aria-invalid={!!err} placeholder="0" />}
            </F>
            {product && (
              <ColourInput label="Colour of this stock" value={colour} onChange={typeColour} error={errors.colour}
                hint={variant ? `This variant: ${colourText(variant.colour)}` : colourDiffers ? undefined : "Saved on the new variant"} />
            )}
            {isNew && product && (
              <F label="Specification" error={errors.spec} hint="As on the existing variant unless this stock differs">
                {(id) => <input id={id} className="st-input" value={spec} maxLength={80} onChange={(e) => { setSpec(e.target.value); clear("variant"); }} placeholder="Standard" />}
              </F>
            )}
            {product && (
              <HsnInput value={hsn} onChange={(x) => { setHsn(x); clear("hsn"); }} error={errors.hsn}
                placeholder={product.hsn || "e.g. 1234567890"}
                hint={product.hsn ? `Saved: HSN ${product.hsn} — leave empty to keep it` : "Optional · 10 digits, saved on the product"} />
            )}
            <F label="Placed at (rack / shelf)" wide hint="Optional — leave blank to keep the current spot">
              {(id) => <input id={id} className="st-input" value={location} maxLength={80} onChange={(e) => { setLocation(e.target.value); }} placeholder="e.g. Rack A / Shelf 3" />}
            </F>
          </div>
          {isNew && product && variants.length > 0 && !twin && (
            <p className="as-note">A new variant will be created{colour.trim() ? ` in ${tidyColour(colour)}` : ""}. Existing variants and their stock stay as they are.</p>
          )}
          {product && (
            <dl className="as-summary" aria-live="polite">
              <div><dt>Current stock{storeSlug ? "" : " (choose a store)"}</dt><dd className="as-mono">{isNew ? 0 : current}</dd></div>
              <div><dt>Adding</dt><dd className="as-mono">+{qty}</dd></div>
              <div><dt>After saving</dt><dd className="as-mono">{(isNew ? 0 : current) + qty}</dd></div>
            </dl>
          )}
          {product && <SerialNote name={product.display_name} quantity={qty} />}
        </section>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- *
 * The modal
 * ---------------------------------------------------------------- */

export default function AddStockModal({ stockPoints, onClose, onAdded }) {
  const [entry, setEntry] = useState("new"); // new | existing
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef(null);
  const submitRef = useRef(null);
  const registerSubmit = useCallback((fn) => { submitRef.current = fn; }, []);
  const scrollTo = useCallback(() => {
    requestAnimationFrame(() => bodyRef.current?.querySelector('[aria-invalid="true"], .as-tiles[data-invalid], .st-alert, .st-err')
      ?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, []);

  // X, Escape and Cancel close at once and switching workflows is immediate:
  // nothing asks first. Unmounting / remounting a form discards its unsaved
  // state. Only an in-progress save holds the modal open (the dialog's `busy`).
  // The handler keeps one identity, so the dialog doesn't re-focus on each render.
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });
  const close = useCallback(() => closeRef.current?.(), []);
  const switchTo = (id) => {
    if (id !== entry && !busy) setEntry(id);
  };
  const props = { stockPoints, setBusy, onAdded, registerSubmit, scrollTo };

  return (
    <Dialog size="wide" title="Add Stock" busy={busy} onClose={close} labelledBy="as-title"
      subtitle={entry === "new" ? "Add a product that isn't in the catalogue yet and receive its units into a store." : "Receive more units of a catalogue product into a store."}
      headExtra={<span className="as-head-icon" aria-hidden="true"><PackagePlus size={20} /></span>}
      footer={(
        <div className="as-foot">
          <button type="button" className="st-btn" onClick={close} disabled={busy}>Cancel</button>
          <button type="button" className="st-btn" data-variant="primary" onClick={() => submitRef.current?.()} disabled={busy}>
            <Save size={15} aria-hidden="true" />{busy ? "Saving…" : entry === "new" ? "Save product & stock" : "Add stock"}
          </button>
        </div>
      )}>
      <div ref={bodyRef} className="as" aria-busy={busy}>
        <section className="as-section as-entry" aria-labelledby="as-entry-title">
          <h3 id="as-entry-title" className="as-section-title">Product entry type</h3>
          <div className="as-segment" role="radiogroup" aria-labelledby="as-entry-title">
            {[["new", "New Product", PackagePlus], ["existing", "Existing Product", PackageCheck]].map(([id, label, Icon]) => (
              <button key={id} type="button" role="radio" aria-checked={entry === id} disabled={busy} onClick={() => switchTo(id)}>
                <Icon size={15} aria-hidden="true" />{label}
              </button>
            ))}
          </div>
        </section>
        {entry === "new" ? <NewProductForm key="new" {...props} /> : <ExistingProductForm key="existing" {...props} />}
      </div>
    </Dialog>
  );
}
