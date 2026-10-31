import { useId, useState } from "react";
import { api } from "../../lib/api";
import { apiErrors } from "../settings/errors";
import { Alert, Dialog, Field, SelectInput, TextInput } from "../settings/StaffUi";
import "../settings/staff.css";

/*
 * Add / edit one shop or online channel (catalog.StockPoint) -- Owner /
 * Super Admin only; the backend refuses anyone else. An edit PATCHes the
 * same record, so its id and everything linked to it stay put.
 *
 * Fields are exactly what the model stores. There are no separate city /
 * state / pincode or active-status columns, so city, state and pincode
 * are written as lines of the address (as the invoice "sold from" block
 * already prints it).
 */

const PHONE_RE = /^\+?[\d\s\-()]+$/;
const GSTIN_RE = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const FIELDS = ["name", "kind", "address", "phone", "gstin"];

function TextArea({ label, hint, error, value, onChange, rows = 4, placeholder }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} id={id}>
      <textarea
        id={id} className="st-input sl-textarea" rows={rows} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
      />
    </Field>
  );
}

function validateStore(form, { editing, points = [], selfId = null } = {}) {
  const errors = {};
  const name = form.name.trim().replace(/\s+/g, " ");
  if (!name) errors.name = "Enter the store or channel name.";
  else if (name.length > 80) errors.name = "Keep the name to 80 characters or fewer.";
  else if (points.some((p) => p.id !== selfId && p.name.trim().toLowerCase() === name.toLowerCase())) {
    errors.name = `Another store or channel is already called “${name}”.`;
  }
  if (!editing && form.slug.trim() && !SLUG_RE.test(form.slug.trim())) {
    errors.slug = "Use lowercase letters, digits and single hyphens only (e.g. karol-bagh).";
  }
  const phone = form.phone.trim();
  const digits = phone.replace(/\D/g, "").length;
  if (phone && phone !== (form.initialPhone || "") && (!PHONE_RE.test(phone) || digits < 7 || digits > 15)) {
    errors.phone = "Enter a valid phone number (7–15 digits; +, spaces, hyphens allowed).";
  }
  const gstin = form.gstin.trim().toUpperCase();
  if (gstin && gstin !== (form.initialGstin || "") && !GSTIN_RE.test(gstin)) {
    errors.gstin = "Enter a valid 15-character GSTIN (e.g. 07ABCDE1234F1Z5), or leave it blank.";
  }
  return errors;
}

export default function StoreForm({ store, points, onClose, onSaved }) {
  const editing = !!store;
  const [form, setForm] = useState({
    name: store?.name || "", kind: store?.kind || "shop", slug: store?.slug || "",
    address: store?.address || "", phone: store?.phone || "", gstin: store?.gstin || "",
    initialPhone: store?.phone || "", initialGstin: store?.gstin || "",
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => { setForm((f) => ({ ...f, [k]: v })); setErrors((e) => ({ ...e, [k]: undefined, _form: undefined })); };

  const submit = async (e) => {
    e.preventDefault();
    const local = validateStore(form, { editing, points, selfId: store?.id });
    if (Object.keys(local).length) { setErrors(local); return; }
    const body = {
      name: form.name.trim().replace(/\s+/g, " "), kind: form.kind, address: form.address.trim(),
      phone: form.phone.trim(), gstin: form.gstin.trim().toUpperCase(),
    };
    if (!editing && form.slug.trim()) body.slug = form.slug.trim();
    if (editing) {
      // send only what changed, so a concurrent edit to another field isn't overwritten
      FIELDS.forEach((k) => { if (body[k] === (store[k] || "")) delete body[k]; });
      if (!Object.keys(body).length) { onClose(); return; }
    }
    setBusy(true);
    try {
      const saved = editing ? await api.patch(`/stock-points/${store.id}/`, body) : await api.post("/stock-points/", body);
      onSaved(saved, editing);
    } catch (err) {
      setErrors(apiErrors(err, editing ? "Couldn't save the store details." : "Couldn't create the store."));
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={editing ? `Edit ${store.name}` : "Add store or channel"} busy={busy} onClose={onClose} labelledBy="sl-store-form-title"
      subtitle={editing
        ? "Changes show everywhere this store appears — inventory, staff, repairs, invoices and reports. Its records stay linked."
        : "A physical shop holds stock and staff; an online channel holds stock only."}
      footer={<>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" form="sl-store-form" className="st-btn" data-variant="primary" disabled={busy}>
          {busy ? "Saving…" : editing ? "Save changes" : "Add store"}
        </button>
      </>}
    >
      <form id="sl-store-form" onSubmit={submit} noValidate className="st-grid">
        {errors._form && <Alert>{errors._form}</Alert>}
        <TextInput label="Name" value={form.name} onChange={set("name")} error={errors.name} autoComplete="off" autoFocus
          placeholder="e.g. Karol Bagh Store" />
        <div className="st-grid" data-cols="2">
          <SelectInput label="Type" value={form.kind} onChange={set("kind")} error={errors.kind}
            hint={editing && store.kind === "shop" ? "A shop with staff or repair tickets can't become an online channel." : undefined}>
            <option value="shop">Physical shop</option>
            <option value="online">Online channel</option>
          </SelectInput>
          {editing ? (
            <div className="st-field">
              <span className="st-label">Store code</span>
              <span className="st-input flex items-center" aria-readonly="true">{store.slug}</span>
              <span className="st-help">Fixed once created — filters and imports refer to it.</span>
            </div>
          ) : (
            <TextInput label="Store code (optional)" value={form.slug} onChange={(v) => set("slug")(v.toLowerCase())} error={errors.slug}
              autoComplete="off" placeholder="e.g. karol-bagh" hint="Left blank, it's made from the name. Can't be changed later." />
          )}
        </div>
        <TextArea label={form.kind === "shop" ? "Address" : "Address (optional)"} value={form.address} onChange={set("address")} error={errors.address}
          placeholder={"Shop no. / building, street\nArea, City\nState – Pincode"}
          hint="Printed on invoices raised here. Put city, state and pincode on their own lines." />
        <div className="st-grid" data-cols="2">
          <TextInput label="Phone (optional)" type="tel" value={form.phone} onChange={set("phone")} error={errors.phone} autoComplete="off"
            hint="Blank uses the business phone on invoices." />
          <TextInput label="GSTIN (optional)" value={form.gstin} onChange={(v) => set("gstin")(v.toUpperCase())} error={errors.gstin}
            autoComplete="off" hint="Only if this branch is registered separately." />
        </div>
      </form>
    </Dialog>
  );
}
