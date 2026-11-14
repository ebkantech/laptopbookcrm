import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Boxes, CircleHelp, PackageCheck, PackagePlus, PencilLine, Plus, Save, Search, Store,
} from "lucide-react";
import { api } from "../../lib/api";
import { loadSuppliers } from "../../components/parties/suppliers";
import { CategoryContext, categoryRegistry, loadCategories, useCategories } from "./categories";
import CategoryEditor from "./CategoryEditor";
import { useSession } from "../../context/SessionContext";
import { isAdminLevel } from "../../lib/accessLevel";
import { money, todayISO } from "../../lib/theme";
import { phoneError } from "../../lib/phone";
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

/* Who the stock was bought from (a Supplier in Parties) and their bill number:
   optional, but it's what the supplier profit comparison is built on. */
function SupplierInputs({ supplier, billNo, onSupplier, onBillNo, error, paidMethod = "", onPaidMethod }) {
  const { can } = useSession();
  const canAdd = can("parties.manage");
  const [suppliers, setSuppliers] = useState(null);
  // "+ New supplier": a small form right here, so a new supplier doesn't mean leaving Add stock
  const [adding, setAdding] = useState(null); // { name, phone, city, gstin }
  const [addErrors, setAddErrors] = useState({});
  const [saving, setSaving] = useState(false);
  useEffect(() => { loadSuppliers().then(setSuppliers, () => setSuppliers([])); }, []);

  const choose = (value) => {
    if (value === "__new") {
      setAdding({ name: "", phone: "", city: "", gstin: "" });
      setAddErrors({});
      return;
    }
    onSupplier(value);
  };
  const saveSupplier = async () => {
    const e = {};
    if (!adding.name.trim()) e.name = "Enter the supplier's name.";
    const badPhone = phoneError(adding.phone);
    if (badPhone) e.phone = badPhone;
    if (!adding.city.trim()) e.city = "Enter the supplier's city.";
    if (Object.keys(e).length) return setAddErrors(e);
    setSaving(true);
    try {
      const created = await api.post("/parties/", {
        name: adding.name.trim(), type: "Supplier", phone: adding.phone.trim(), city: adding.city.trim(), gstin: adding.gstin.trim().toUpperCase(),
        customer_classification: "business", joined: todayISO(),
      });
      setSuppliers(await loadSuppliers(true));
      onSupplier(String(created.id));
      setAdding(null);
    } catch (err) {
      const b = err.body || {};
      setAddErrors(Object.fromEntries(Object.entries(b).map(([k, v]) => [k, [].concat(v).join(" ")])));
    } finally {
      setSaving(false);
    }
  };

  const noneYet = suppliers && !suppliers.length;
  return (
    <>
      <F label="Bought from (supplier)" error={error}
        hint={noneYet ? (canAdd ? "No suppliers yet — choose “+ New supplier”" : "No suppliers yet — ask an Admin to add one in Parties") : "Optional — needed to compare suppliers' profit"}>
        {(id) => (
          <select id={id} className="st-input" value={adding ? "__new" : supplier} onChange={(e) => choose(e.target.value)}>
            <option value="">{suppliers ? "Not recorded" : "Loading…"}</option>
            {(suppliers || []).map((p) => <option key={p.id} value={p.id}>{p.name}{p.city ? ` · ${p.city}` : ""}</option>)}
            {canAdd && <option value="__new">+ New supplier…</option>}
          </select>
        )}
      </F>
      <F label="Supplier bill no." hint="Optional">
        {(id) => <input id={id} className="st-input" value={billNo} maxLength={60} onChange={(e) => onBillNo(e.target.value)} placeholder="e.g. INV/2026/0412" />}
      </F>
      {supplier && onPaidMethod && (
        <F label="Payment to supplier" wide hint={paidMethod ? "Paid in full now — taken out of the cash / bank book" : "Bought on credit — shows as owed on the supplier's ledger until you pay them"}>
          {(id) => (
            <select id={id} className="st-input" value={paidMethod} onChange={(e) => onPaidMethod(e.target.value)}>
              <option value="">On credit — pay later</option>
              {["Cash", "UPI", "Bank transfer", "Cheque", "Card", "Other"].map((m) => <option key={m} value={m}>Paid now by {m}</option>)}
            </select>
          )}
        </F>
      )}
      {adding && (
        <div className="as-wide as-new-supplier" role="group" aria-label="New supplier">
          <p className="st-label">New supplier — saved in Parties with type Supplier</p>
          <div className="as-grid">
            <F label="Supplier name" required error={addErrors.name}>
              {(id, err) => <input id={id} className="st-input" value={adding.name} maxLength={120} autoFocus aria-invalid={!!err}
                onChange={(e) => setAdding({ ...adding, name: e.target.value })} placeholder="e.g. Alpha Traders" />}
            </F>
            <F label="Mobile" required error={addErrors.phone}>
              {(id, err) => <input id={id} className="st-input" value={adding.phone} inputMode="tel" maxLength={20} aria-invalid={!!err}
                onChange={(e) => setAdding({ ...adding, phone: e.target.value })} placeholder="98xxxxxxxx" />}
            </F>
            <F label="City" required error={addErrors.city}>
              {(id) => <input id={id} className="st-input" value={adding.city} maxLength={60} onChange={(e) => setAdding({ ...adding, city: e.target.value })} />}
            </F>
            <F label="GSTIN" hint="Optional" error={addErrors.gstin}>
              {(id) => <input id={id} className="st-input as-mono" value={adding.gstin} maxLength={20} onChange={(e) => setAdding({ ...adding, gstin: e.target.value })} />}
            </F>
          </div>
          {addErrors.detail && <p className="st-err">{addErrors.detail}</p>}
          <div className="as-new-supplier-actions">
            <button type="button" className="st-btn" data-variant="primary" onClick={saveSupplier} disabled={saving}>{saving ? "Saving…" : "Save supplier"}</button>
            <button type="button" className="st-btn" onClick={() => setAdding(null)} disabled={saving}>Cancel</button>
          </div>
        </div>
      )}
    </>
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

/* Purchase cost: what one unit cost the shop. It is what makes Profit & Loss
   real -- left empty, the server uses an estimate (78% of the selling price)
   and flags it so it can be corrected under Inventory -> Costs. */
const COST_ERROR = "Enter the purchase cost of at least ₹1, or leave it empty.";
const costInvalid = (v) => v !== "" && !(Number(v) > 0);

function CostInput({ value, onChange, error, hint }) {
  return (
    <F label="Purchase cost per unit (₹)" error={error} hint={hint}>
      {(id, err) => <input id={id} className="st-input as-mono" inputMode="numeric" value={value} onChange={(e) => onChange(digits(e.target.value))} aria-invalid={!!err} placeholder="What you paid for one unit" />}
    </F>
  );
}

function MarginNote({ cost, sell }) {
  const c = Number(cost), p = Number(sell);
  if (!(c > 0 && p > 0)) return null;
  const margin = p - c;
  return <p className="as-total">Margin per unit: <b className="as-mono" style={margin < 0 ? { color: "var(--st-red, #C83C4A)" } : undefined}>{money(margin)}</b> ({Math.round((margin / p) * 1000) / 10}% of the selling price)</p>;
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

function NewProductForm({ stockPoints, setBusy, onAdded, registerSubmit, scrollTo, onEditCategories }) {
  const cats = useCategories();
  const [category, setCategory] = useState("");
  // the chosen category as the Admin set it up: its fields, * marks, name label...
  const cat = cats.byKey[category];
  const [v, setV] = useState({
    brand: "", model_name: "", description: "", colour: "", hsn: "", condition: "New", specs: {},
    stock_point: stockPoints.length === 1 ? String(stockPoints[0].id) : "", quantity: "1", sell_price: "", mrp: "", cost: "", location: "",
    supplier: "", bill_no: "", paid_method: "",
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
    if (cat && cat.brand_required && !v.brand.trim()) e.brand = "Enter the brand.";
    if (!v.model_name.trim()) e.model_name = `Enter the ${(cat?.name_label || "model / product name").toLowerCase()}.`;
    for (const f of cat?.specFields || []) {
      if (f.required && !(v.specs[category]?.[f.key] || "").trim()) e[`specs.${f.key}`] = `Enter the ${f.label.toLowerCase()}.`;
    }
    if (hsnInvalid(v.hsn)) e.hsn = HSN_ERROR;
    if (v.model_name.trim() && !serialPrefix(`${v.brand} ${v.model_name}`)) e.model_name = "The product name needs at least two letters (A–Z) to make its serial numbers.";
    if (!v.stock_point) e.stock_point = "Choose the store / stock point.";
    if (!(qty > 0)) e.quantity = "Enter a quantity of at least 1.";
    if (!(Number(v.sell_price) > 0)) e.sell_price = "Enter the selling price.";
    if (v.mrp && Number(v.mrp) < Number(v.sell_price)) e.mrp = "MRP can't be lower than the selling price.";
    if (costInvalid(v.cost)) e.cost = COST_ERROR;
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
        colour: tidyColour(v.colour), hsn: v.hsn, specs, ...(cat?.show_condition ? { condition: v.condition } : {}),
        stock_point: Number(v.stock_point), quantity: qty, sell_price: Number(v.sell_price), mrp: v.mrp ? Number(v.mrp) : null,
        cost: v.cost ? Number(v.cost) : null, location: v.location.trim(),
        supplier: v.supplier ? Number(v.supplier) : null, bill_no: v.bill_no.trim(), paid_method: v.supplier ? v.paid_method : "",
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
        <div className="flex items-center justify-between gap-2">
          <h3 id="as-cat-title" className="as-section-title">Product category<span className="as-req" aria-hidden="true"> *</span></h3>
          {onEditCategories && (
            <button type="button" className="st-btn" onClick={onEditCategories} title="Rename categories, change their fields and which are required">
              <PencilLine size={14} aria-hidden="true" />Edit categories
            </button>
          )}
        </div>
        <div className="as-tiles" role="radiogroup" aria-labelledby="as-cat-title" data-invalid={errors.category ? "" : undefined}>
          {cats.active.map((c) => (
            <button key={c.key} type="button" role="radio" aria-checked={category === c.key} className="as-tile"
              onClick={() => { setCategory(c.key); setErrors((e) => ({ ...e, category: undefined })); }}>
              <c.Icon size={22} aria-hidden="true" /><span>{c.name}</span>
            </button>
          ))}
          {!cats.active.length && <p className="as-empty">Loading categories…</p>}
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
              <F label="Brand" required={!!cat?.brand_required} error={errors.brand} hint={cat && !cat.brand_required ? "Optional" : undefined}>
                {(id, err) => <input id={id} className="st-input" value={v.brand} maxLength={40} onChange={(e) => set("brand")(e.target.value)} aria-invalid={!!err} placeholder="e.g. Dell" />}
              </F>
              <F label={cat?.name_label || "Model / product name"} required error={errors.model_name}>
                {(id, err) => <input id={id} className="st-input" value={v.model_name} maxLength={80} onChange={(e) => set("model_name")(e.target.value)} aria-invalid={!!err} placeholder={category === "laptop" ? "e.g. Latitude 5440" : ""} />}
              </F>
              {(cat?.specFields || []).map((f) => (
                <F key={`${category}-${f.key}`} label={f.label} required={f.required} error={errors[`specs.${f.key}`]} wide={f.wide}>
                  {(id, err) => <SpecInput field={f} id={id} value={v.specs[category]?.[f.key] || ""} onChange={setSpec(f.key)} error={err} />}
                </F>
              ))}
              {cat?.show_condition && (
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
            <CostInput value={v.cost} onChange={set("cost")} error={errors.cost}
              hint="Recommended — needed for real profit. Left empty, profit uses an estimate until you enter it." />
            <SupplierInputs supplier={v.supplier} billNo={v.bill_no} onSupplier={set("supplier")} onBillNo={set("bill_no")} error={errors.supplier}
              paidMethod={v.paid_method} onPaidMethod={set("paid_method")} />
            <F label="Placed at (rack / shelf)" wide hint="Optional">
              {(id) => <input id={id} className="st-input" value={v.location} maxLength={80} onChange={(e) => set("location")(e.target.value)} placeholder="e.g. Rack A / Shelf 3" />}
            </F>
            <SerialNote name={`${v.brand} ${v.model_name}`} quantity={qty} />
          </div>
          {Number(v.sell_price) > 0 && qty > 0 && <p className="as-total">Stock value at selling price: <b className="as-mono">{money(Number(v.sell_price) * qty)}</b></p>}
          <MarginNote cost={v.cost} sell={v.sell_price} />
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
  const cats = useCategories();
  const [q, setQ] = useState("");
  const [state, setState] = useState({ q: null, rows: null, error: null });
  useEffect(() => {
    const term = q.trim();
    if (!term) return undefined;
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
      {!term ? <p className="st-help">Start typing to search the catalogue.</p>
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
                          <span className="as-result-sub">{cats.byKey[p.category]?.name || "Uncategorised"} · {p.brand && p.brand !== "—" ? p.brand : "No brand"} · {p.model_name}</span>
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
  const cats = useCategories();
  const fields = cats.byKey[product.category]?.specFields || [];
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
        <div><dt>Category</dt><dd>{cats.byKey[product.category]?.name || "Uncategorised"}</dd></div>
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
  const [cost, setCost] = useState("");
  const [location, setLocation] = useState("");
  const [supplier, setSupplier] = useState("");
  const [billNo, setBillNo] = useState("");
  const [paidMethod, setPaidMethod] = useState("");
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
    if (costInvalid(cost)) e.cost = COST_ERROR;
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
        ...(supplier ? { supplier: Number(supplier), bill_no: billNo.trim(), paid_method: paidMethod } : {}),
        // what this batch cost; the server averages it with the units already in stock
        ...(cost ? { cost: Number(cost) } : {}),
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
            <CostInput value={cost} onChange={(x) => { setCost(x); clear("cost"); }} error={errors.cost}
              hint={variant
                ? variant.cost_estimated || !variant.cost
                  ? `Not entered yet${variant.cost ? ` — profit uses an estimate of ${money(variant.cost)}` : ""}. Enter what this batch cost.`
                  : `Average cost now ${money(variant.cost)} — this batch is averaged in`
                : "Recommended — needed for real profit"} />
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
            <SupplierInputs supplier={supplier} billNo={billNo} onSupplier={(x) => { setSupplier(x); clear("supplier"); }} onBillNo={setBillNo} error={errors.supplier}
              paidMethod={paidMethod} onPaidMethod={setPaidMethod} />
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
          {product && <MarginNote cost={cost} sell={sell || variant?.sell_price} />}
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
  const { me } = useSession();
  const [entry, setEntry] = useState("new"); // new | existing
  // product categories and their fields come from the server: an Admin edits them here
  const [categories, setCategories] = useState([]);
  const [editingCategories, setEditingCategories] = useState(false);
  const [categoryError, setCategoryError] = useState("");
  const reloadCategories = useCallback(() => loadCategories().then(setCategories, (e) => setCategoryError(e.message)), []);
  useEffect(() => { reloadCategories(); }, [reloadCategories]);
  const registry = useMemo(() => categoryRegistry(categories), [categories]);
  const canEditCategories = isAdminLevel(me);
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
  const props = { stockPoints, setBusy, onAdded, registerSubmit, scrollTo, onEditCategories: canEditCategories ? () => setEditingCategories(true) : null };

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
        {categoryError && <Alert>Categories couldn't be loaded: {categoryError}</Alert>}
        <CategoryContext.Provider value={registry}>
          {entry === "new" ? <NewProductForm key="new" {...props} /> : <ExistingProductForm key="existing" {...props} />}
        </CategoryContext.Provider>
      </div>
      {editingCategories && (
        <CategoryEditor categories={categories} onClose={() => setEditingCategories(false)}
          onSaved={(list) => setCategories(list)} />
      )}
    </Dialog>
  );
}
