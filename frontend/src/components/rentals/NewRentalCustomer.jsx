import { useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, todayISO } from "../../lib/theme";
import { ErrorNote } from "../Atoms";
import { CUSTOMER_LIMITS, customerPayload, findSamePhone, validateCustomer } from "./customerValidation";

const box = (message) => ({ border: `1px solid ${message ? C.carbon : C.rule}`, color: C.ink, fontFamily: F.body });

/*
 * Add a rental customer without leaving the rental agreement form. Always
 * saved as a Rental customer; the new customer is selected for the agreement.
 * (Not a <form>: it sits inside the agreement's own form.)
 */
export default function NewRentalCustomer({ parties, onCancel, onCreated }) {
  const [form, setForm] = useState({ name: "", phone: "", email: "", city: "", gstin: "", customer_classification: "individual" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const duplicate = findSamePhone(parties, form.phone);

  const set = (key) => (e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setErrors((old) => ({ ...old, [key]: "" })); };

  const save = async () => {
    setError("");
    const found = validateCustomer(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      onCreated(await api.post("/parties/", customerPayload(form, todayISO())));
    } catch (e) {
      const body = e.body || {};
      const fields = Object.fromEntries(Object.entries(body).filter(([k]) => k !== "detail").map(([k, v]) => [k, [].concat(v).join(" ")]));
      setErrors(fields);
      setError(body.detail || (Object.keys(fields).length ? "Please correct the highlighted fields." : e.message));
    } finally {
      setBusy(false);
    }
  };

  const input = (label, key, props = {}) => (
    <label className="block min-w-0 text-xs" style={{ color: C.inkSoft }}>{label}
      <input value={form[key]} onChange={set(key)} aria-invalid={!!errors[key]} maxLength={CUSTOMER_LIMITS[key]} className="mt-1 w-full bg-transparent px-2 py-1.5 text-sm outline-none" style={box(errors[key])} {...props} />
      {errors[key] && <span role="alert" className="mt-1 block text-xs" style={{ color: C.carbon, fontWeight: 600 }}>{errors[key]}</span>}
    </label>
  );

  return (
    <div className="mt-3 p-3" data-testid="new-customer-panel" style={{ border: `1px solid ${C.stamp}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>New rental customer</span>
        <button type="button" onClick={onCancel} aria-label="Cancel new customer" className="-m-1.5 flex h-8 w-8 items-center justify-center rounded-full hover:bg-black/5"><X size={14} style={{ color: C.inkSoft }} /></button>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {input("Name *", "name", { autoFocus: true, "aria-label": "Customer name" })}
        {input("Mobile *", "phone", { placeholder: "98xxxxxxxx", inputMode: "tel", "aria-label": "Customer mobile" })}
        {input("Email *", "email", { type: "email", "aria-label": "Customer email" })}
        {input("City *", "city", { "aria-label": "Customer city" })}
        <label className="block min-w-0 text-xs" style={{ color: C.inkSoft }}>Customer kind
          <select value={form.customer_classification} onChange={set("customer_classification")} className="mt-1 w-full bg-transparent px-2 py-1.5 text-sm outline-none" style={box()}>
            <option value="individual">Individual</option><option value="business">Business / Corporate</option>
          </select>
        </label>
        {input("GSTIN (optional)", "gstin", { placeholder: "Business customers only", "aria-label": "Customer GSTIN" })}
      </div>
      {duplicate && (
        <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.amber }}>
          This number already belongs to <b>{duplicate.name}</b>.{" "}
          <button type="button" onClick={() => onCreated(duplicate, { existing: true })} className="underline" style={{ color: C.stamp, fontWeight: 600 }}>Use {duplicate.name} instead</button>
        </p>
      )}
      <ErrorNote message={error} />
      <button type="button" onClick={save} disabled={busy} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
        <Check size={12} /> {busy ? "Saving…" : "Save customer and use here"}
      </button>
    </div>
  );
}
