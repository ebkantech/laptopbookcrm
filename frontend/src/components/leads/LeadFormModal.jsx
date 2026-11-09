import { useEffect, useMemo, useState } from "react";
import { UserPlus } from "lucide-react";
import { api } from "../../lib/api";
import { C, F, todayISO } from "../../lib/theme";
import { ErrorNote } from "../Atoms";
import { leadPayload, validateLeadForm, PRIORITY } from "./leadModel";
import { findSamePhone, validateCustomer } from "../rentals/customerValidation";
import { Modal, inputStyle } from "./Prompt";

const toLocalInput = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function Field({ label, error, children, className = "" }) {
  return (
    <label className={`block text-xs ${className}`} style={{ fontFamily: F.body, color: C.inkSoft }}>
      {label}{children}{error && <span className="mt-1 block" style={{ color: C.carbon }}>{error}</span>}
    </label>
  );
}

/* Create (lead = null) or edit an on-site job. */
export default function LeadFormModal({ lead, stockPoints, defaultStore, onClose, onSaved }) {
  const [parties, setParties] = useState([]);
  const [techs, setTechs] = useState([]);
  const [form, setForm] = useState(() => ({
    party: lead?.party ?? "", stock_point: lead?.stock_point ?? defaultStore ?? stockPoints[0]?.id ?? "",
    contact_name: lead?.contact_name ?? "", contact_phone: lead?.contact_phone ?? "", site_address: lead?.site_address ?? "",
    map_url: lead?.map_url ?? "", device: lead?.device ?? "", issue: lead?.issue ?? "", priority: lead?.priority ?? "normal",
    preferred_at: toLocalInput(lead?.preferred_at), assigned_to: lead?.assigned_to ?? "",
    visit_charge: String(lead?.visit_charge ?? 300), advance_amount: lead?.advance_amount ? String(lead.advance_amount) : "",
  }));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [newCust, setNewCust] = useState(null);

  useEffect(() => { api.getAll("/parties/").then(setParties).catch(() => {}); }, []);
  useEffect(() => {
    api.get(`/leads/technicians/${form.stock_point ? `?stock_point=${form.stock_point}` : ""}`).then(setTechs).catch(() => setTechs([]));
  }, [form.stock_point]);

  const set = (key) => (e) => { const v = e.target.value; setForm((f) => ({ ...f, [key]: v })); setErrors((o) => ({ ...o, [key]: "" })); };
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return parties.filter((p) => !q || p.name.toLowerCase().includes(q) || (p.phone || "").includes(q)).slice(0, 50);
  }, [parties, query]);

  const pickParty = (id) => {
    const p = parties.find((x) => String(x.id) === String(id));
    setForm((f) => ({ ...f, party: id, contact_name: f.contact_name || p?.name || "", contact_phone: f.contact_phone || p?.phone || "" }));
    setErrors((o) => ({ ...o, party: "" }));
  };

  // Either pick an existing customer OR add a new one -- never both at once.
  // Opening "New" drops the customer picked from the list (and the site
  // contact copied from them), and hides the list until the new one is
  // added or the form is cancelled.
  const startNewCustomer = () => {
    const picked = parties.find((x) => String(x.id) === String(form.party));
    setForm((f) => ({
      ...f, party: "",
      contact_name: picked && f.contact_name === picked.name ? "" : f.contact_name,
      contact_phone: picked && f.contact_phone === picked.phone ? "" : f.contact_phone,
    }));
    setNewCust({ name: query.trim() && !/^\d+$/.test(query.trim()) ? query.trim() : "", phone: /^\d+$/.test(query.trim()) ? query.trim() : "", email: "", city: "", errors: {} });
  };

  const createCustomer = async () => {
    const found = validateCustomer({ ...newCust, gstin: "" });
    if (Object.keys(found).length) return setNewCust({ ...newCust, errors: found });
    const dup = findSamePhone(parties, newCust.phone);
    if (dup) { pickParty(dup.id); return setNewCust(null); }
    try {
      const party = await api.post("/parties/", {
        name: newCust.name.trim(), phone: newCust.phone.trim(), email: newCust.email.trim(), city: newCust.city.trim(),
        type: "Retail", customer_classification: "individual", joined: todayISO(),
      });
      setParties((all) => [party, ...all]);
      pickParty(party.id);
      setNewCust(null);
    } catch (e) {
      const body = e.body || {};
      const errors = {};
      ["name", "phone", "email", "city"].forEach((k) => { if (body[k]) errors[k] = [].concat(body[k]).join(" "); });
      setNewCust({ ...newCust, errors, error: Object.keys(errors).length ? "" : body.detail || e.message });
    }
  };

  const save = async (e) => {
    e.preventDefault();
    const found = validateLeadForm(form);
    if (found.party && newCust) found.party = "Press “Add customer” to save the new customer first.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const payload = leadPayload(form);
      const saved = lead ? await api.patch(`/leads/${lead.id}/`, payload) : await api.post("/leads/", payload);
      onSaved(saved);
    } catch (err) {
      const body = err.body || {};
      const fieldErrors = {};
      Object.keys(body).forEach((k) => { if (k !== "detail") fieldErrors[k] = [].concat(body[k]).join(" "); });
      setErrors(fieldErrors);
      setError(body.detail || (Object.keys(fieldErrors).length ? "Please fix the highlighted fields." : err.message));
      setBusy(false);
    }
  };

  const input = (key, props = {}) => (
    <input value={form[key]} onChange={set(key)} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(errors[key])} {...props} />
  );

  return (
    <Modal title={lead ? `Edit ${lead.code}` : "New on-site job"} onClose={onClose} wide>
      <form onSubmit={save} noValidate className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Customer *" error={errors.party}>
            {!newCust && <>
            <div className="mt-1 flex gap-2">
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search customer" aria-label="Search customer" className="min-w-0 flex-1 bg-transparent px-2.5 py-1 text-sm outline-none sm:max-w-[200px]" style={inputStyle(false)} />
              <button type="button" onClick={startNewCustomer} className="flex shrink-0 items-center gap-1 px-3 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink }}><UserPlus size={13} /> New</button>
            </div>
            <select value={form.party} onChange={(e) => pickParty(e.target.value)} className="mt-2 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(errors.party)}>
              <option value="">Select customer…</option>
              {matches.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.phone}</option>)}
            </select>
            </>}
          </Field>
          {newCust && (
            <div className="mt-1 grid gap-2 p-3 sm:grid-cols-2" style={{ border: `1px dashed ${C.rule}` }}>
              <p className="text-xs sm:col-span-2" style={{ color: C.inkSoft, fontFamily: F.body, fontWeight: 700 }}>New customer — or <button type="button" onClick={() => setNewCust(null)} className="underline" style={{ color: C.blue }}>choose an existing one</button></p>
              {[["name", "Customer name", "Name *", "text"], ["phone", "Mobile number", "Mobile *", "tel"], ["email", "name@example.com", "Email *", "email"], ["city", "City", "City *", "text"]].map(([k, ph, label, type]) => (
                <label key={k} className="block text-xs" style={{ color: C.inkSoft, fontFamily: F.body }}>{label}
                  <input value={newCust[k]} type={type} onChange={(e) => setNewCust({ ...newCust, [k]: e.target.value, errors: { ...newCust.errors, [k]: "" }, error: "" })} placeholder={ph} aria-label={`New customer ${k}`}
                    className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(newCust.errors?.[k])} />
                  {newCust.errors?.[k] && <span className="mt-1 block" style={{ color: C.carbon }}>{newCust.errors[k]}</span>}
                </label>
              ))}
              {newCust.error && <p className="text-xs sm:col-span-2" style={{ color: C.carbon }}>{newCust.error}</p>}
              <div className="flex gap-2 sm:col-span-2"><button type="button" onClick={createCustomer} className="px-4 py-2 text-xs" style={{ backgroundColor: C.orange, color: C.onAccent, fontWeight: 700 }}>Add customer</button><button type="button" onClick={() => setNewCust(null)} className="px-4 py-2 text-xs" style={{ border: `1px solid ${C.rule}` }}>Cancel</button></div>
            </div>
          )}
        </div>
        <Field label="Store *" error={errors.stock_point}>
          <select value={form.stock_point} onChange={set("stock_point")} disabled={!!lead || stockPoints.length === 1} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(errors.stock_point)}>
            <option value="">Select store…</option>
            {stockPoints.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
        <Field label="Priority"><select value={form.priority} onChange={set("priority")} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>{Object.entries(PRIORITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Contact at site" error={errors.contact_name}>{input("contact_name", { placeholder: "Name" })}</Field>
        <Field label="Contact phone" error={errors.contact_phone}>{input("contact_phone", { placeholder: "Mobile number", inputMode: "tel" })}</Field>
        <Field label="Site address *" error={errors.site_address} className="sm:col-span-2">{input("site_address", { placeholder: "Shop / house no., street, area, city" })}</Field>
        <Field label="Map link (optional)" error={errors.map_url} className="sm:col-span-2">{input("map_url", { placeholder: "https://maps.app.goo.gl/…" })}</Field>
        <Field label="Laptop (brand / model)" error={errors.device}>{input("device", { placeholder: "e.g. Dell Latitude 5420" })}</Field>
        <Field label="Preferred visit time" error={errors.preferred_at}>{input("preferred_at", { type: "datetime-local" })}</Field>
        <Field label="Problem reported *" error={errors.issue} className="sm:col-span-2">
          <textarea value={form.issue} onChange={set("issue")} rows={3} placeholder="What the client says is wrong" className="mt-1 w-full resize-none bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(errors.issue)} />
        </Field>
        <Field label="Assign to technician" error={errors.assigned_to}>
          <select value={form.assigned_to} onChange={set("assigned_to")} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(errors.assigned_to)}>
            <option value="">Assign later</option>
            {techs.map((t) => <option key={t.id} value={t.id}>{t.kind === "outsourced" ? `${t.name} — Outsourced · ${t.company}` : t.kind === "field" ? `${t.name} — Field technician` : t.name}</option>)}
          </select>
        </Field>
        <Field label="Visit charge (₹)" error={errors.visit_charge}>{input("visit_charge", { inputMode: "numeric" })}</Field>
        {!lead && <Field label="Advance asked (₹, optional)" error={errors.advance_amount}>{input("advance_amount", { inputMode: "numeric", placeholder: "Leave blank for none" })}</Field>}
        <div className="sm:col-span-2"><ErrorNote message={error} />
          <div className="mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={onClose} className="min-h-[44px] px-4 py-2 text-xs" style={{ border: `1px solid ${C.rule}` }}>Cancel</button>
            <button disabled={busy} className="min-h-[44px] px-5 py-2 text-xs uppercase" style={{ backgroundColor: C.orange, color: C.onAccent, fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>{busy ? "Saving…" : lead ? "Save changes" : "Create job"}</button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
