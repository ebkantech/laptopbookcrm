import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Copy, FileText, ImageIcon, Paperclip, Plus, Save, Trash2, X } from "lucide-react";
import { api } from "../../lib/api";
import { money, todayISO } from "../../lib/theme";
import { Alert, Dialog, Field } from "../settings/StaffUi";
import { fileSize } from "./format";

/*
 * Accounting -> Expenses -> Add expenses: several expenses in one save.
 * POST /expenses/bulk/ (multipart): `entries` (JSON, in card order),
 * `attachments_<n>` = the files of card n only, and `submission_key` --
 * one per open form, so a double click or a retried request is saved once
 * (accounting.expenses.create_bulk). The backend validates every entry
 * before writing anything and saves all of them or none.
 */

const newUid = () => (globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`);
const newKey = () => newUid().replace(/[^A-Za-z0-9-]/g, "");

const extOf = (name) => (name.match(/\.[^.]+$/)?.[0] || "").toLowerCase();

function blankEntry(defaultStore) {
  return {
    uid: newUid(), store: defaultStore ? String(defaultStore) : "", category: "", expense_date: todayISO(), amount: "",
    gst_amount: "", gst_claimable: false, vendor: "", reference: "", description: "",
    payment_status: "paid", payment_method: "Cash", payment_date: todayISO(), paid_amount: "", payment_reference: "", files: [],
  };
}

const digits = (v) => v.replace(/\D/g, "").slice(0, 10);
const int = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

/* The same rules the backend applies, so most mistakes show before saving.
   The backend still checks everything (and file contents). */
function checkEntry(e, limits) {
  const err = {};
  const today = todayISO();
  if (!e.store) err.stock_point = "Choose a store, or Shared / head office.";
  if (!e.category) err.category = "Choose a category.";
  if (!e.expense_date) err.expense_date = "Enter the expense date.";
  else if (e.expense_date > today) err.expense_date = "The expense date can't be in the future.";
  if (!(int(e.amount) > 0)) err.amount = "Enter the amount in whole rupees.";
  if (int(e.gst_amount) > int(e.amount)) err.gst_amount = "GST can't be more than the bill amount.";
  if (e.payment_status !== "unpaid") {
    if (!e.payment_method) err.payment_method = "Choose how it was paid.";
    if (!e.payment_date) err.payment_date = "Enter the date it was paid.";
    else if (e.payment_date > today) err.payment_date = "The payment date can't be in the future.";
    if (e.payment_status === "partial") {
      if (!(int(e.paid_amount) > 0)) err.paid_amount = "Enter how much was paid.";
      else if (int(e.paid_amount) >= int(e.amount)) err.paid_amount = "A part payment must be less than the amount — choose Paid if it's settled.";
    }
  }
  if (limits) {
    if (e.files.length > limits.max_files_per_expense) err.attachments = `At most ${limits.max_files_per_expense} attachments per expense.`;
    const bad = e.files.find((f) => !limits.extensions.includes(extOf(f.name)) || f.size > limits.max_file_bytes || f.size === 0);
    if (bad) err.attachments = `${bad.name}: use JPG, JPEG, PNG or PDF up to ${fileSize(limits.max_file_bytes)}.`;
  }
  return err;
}

function toPayload(e) {
  const shared = e.store === "shared";
  return {
    stock_point: shared ? null : int(e.store), shared, category: int(e.category), expense_date: e.expense_date,
    amount: int(e.amount), gst_amount: int(e.gst_amount) || 0, gst_claimable: !!e.gst_claimable && int(e.gst_amount) > 0,
    vendor: e.vendor.trim(), reference: e.reference.trim(), description: e.description.trim(),
    payment_status: e.payment_status,
    ...(e.payment_status === "unpaid" ? {} : {
      payment_method: e.payment_method, payment_date: e.payment_date, payment_reference: e.payment_reference.trim(),
      ...(e.payment_status === "partial" ? { paid_amount: int(e.paid_amount) } : {}),
    }),
  };
}

// Backend field errors -> one message per form field.
function flatten(errors = {}) {
  const out = {};
  for (const [k, v] of Object.entries(errors)) out[k] = Array.isArray(v) ? v.join(" ") : String(v);
  return out;
}

/* ---------------------------------------------------------------- */

export function StorePicker({ id, value, onChange, stores, canShared, error }) {
  return (
    <select id={id} className="st-input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} required>
      <option value="">Choose…</option>
      {stores.map((s) => <option key={s.id} value={s.id}>{s.name}{s.is_active === false ? " (inactive)" : ""}</option>)}
      {canShared && <option value="shared">Shared / head office (not a store)</option>}
    </select>
  );
}

function F({ label, error, hint, children, wide }) {
  const id = useId();
  return (
    <div className={wide ? "ex-span" : undefined}>
      <Field id={id} label={label} error={error} hint={hint}>{children(id, error)}</Field>
    </div>
  );
}

function Attachments({ files, onChange, limits, error, number }) {
  const input = useRef(null);
  const add = (list) => {
    const picked = [...list];
    // the same file twice in one expense is almost always a slip
    const seen = new Set(files.map((f) => `${f.name}:${f.size}`));
    onChange([...files, ...picked.filter((f) => !seen.has(`${f.name}:${f.size}`))]);
    if (input.current) input.current.value = "";
  };
  return (
    <div className="ex-span ex-files">
      <div className="ex-files-head">
        <span className="st-label">Attachments <small>· JPG, PNG or PDF{limits ? `, up to ${fileSize(limits.max_file_bytes)} each` : ""}</small></span>
        <button type="button" className="st-btn" onClick={() => input.current?.click()}>
          <Paperclip size={14} aria-hidden="true" />Add files
        </button>
        <input ref={input} type="file" multiple hidden accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
          aria-label={`Attachments for expense ${number}`} onChange={(e) => add(e.target.files)} />
      </div>
      {files.length > 0 && (
        <ul className="ex-file-list">
          {files.map((f, i) => (
            <li key={`${f.name}-${f.size}-${f.lastModified}`}>
              {extOf(f.name) === ".pdf" ? <FileText size={15} aria-hidden="true" /> : <ImageIcon size={15} aria-hidden="true" />}
              <span className="ex-file-name" title={f.name}>{f.name}</span>
              <span className="ex-file-size">{fileSize(f.size)}</span>
              <button type="button" className="st-icon-btn" onClick={() => onChange(files.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="st-err">{error}</p>}
    </div>
  );
}

function EntryCard({ entry, number, total, onChange, onRemove, onDuplicate, errors, meta, stores, refEl }) {
  const set = (k) => (v) => onChange({ ...entry, [k]: v });
  const paid = entry.payment_status !== "unpaid";
  const count = Object.keys(errors).length;
  const moreOpen = ["reference", "gst_amount", "description", "attachments"].some((k) => errors[k])
    || !!(entry.reference || entry.gst_amount || entry.description || entry.files.length);
  return (
    <section ref={refEl} className="ex-card" data-invalid={count > 0 || undefined} aria-labelledby={`ex-entry-${entry.uid}`}>
      <header className="ex-card-head">
        <h3 id={`ex-entry-${entry.uid}`} className="ex-card-title">
          <span className="ex-num">{number}</span>Expense {number}
          {int(entry.amount) > 0 && <span className="ex-card-amt">{money(int(entry.amount))}</span>}
        </h3>
        {count > 0 && <span className="ex-flag"><AlertTriangle size={12} aria-hidden="true" />{count} to fix</span>}
        <div className="ex-card-actions">
          <button type="button" className="st-btn" onClick={onDuplicate} title="Copy this entry's details into a new one (attachments aren't copied)">
            <Copy size={14} aria-hidden="true" /><span className="ex-hide-sm">Duplicate</span>
          </button>
          {total > 1 && (
            <button type="button" className="st-btn" data-tone="danger" onClick={onRemove} aria-label={`Remove expense ${number}`}>
              <Trash2 size={14} aria-hidden="true" /><span className="ex-hide-sm">Remove</span>
            </button>
          )}
        </div>
      </header>

      {/* the essentials: what, how much, when, where */}
      <div className="ex-span" role="radiogroup" aria-label={`Category of expense ${number}`}>
        <span className="st-label">What was it for? *</span>
        <div className="ex-catpick">
          {meta.categories.filter((c) => c.is_active).map((c) => (
            <button key={c.id} type="button" role="radio" aria-checked={String(entry.category) === String(c.id)} onClick={() => set("category")(String(c.id))}>{c.label}</button>
          ))}
        </div>
        {errors.category && <p className="st-err">{errors.category}</p>}
      </div>
      <div className="ex-grid ex-grid-main">
        <F label="Amount (₹) *" error={errors.amount} hint="Bill total, including any GST">
          {(id, err) => <input id={id} inputMode="numeric" className="st-input ex-mono ex-amount" value={entry.amount} onChange={(e) => set("amount")(digits(e.target.value))} placeholder="0" aria-invalid={!!err} required />}
        </F>
        <F label="Date *" error={errors.expense_date}>
          {(id, err) => <input id={id} type="date" className="st-input" value={entry.expense_date} max={todayISO()} onChange={(e) => set("expense_date")(e.target.value)} aria-invalid={!!err} required />}
        </F>
        <F label="Store *" error={errors.stock_point}>
          {(id, err) => <StorePicker id={id} value={entry.store} onChange={set("store")} stores={stores} canShared={meta.can_record_shared} error={err} />}
        </F>
        <F label="Paid to" error={errors.vendor} hint="Shop, landlord, person…">
          {(id) => <input id={id} className="st-input" value={entry.vendor} maxLength={120} onChange={(e) => set("vendor")(e.target.value)} />}
        </F>
      </div>

      {/* paid or not */}
      <div className="ex-pay" role="group" aria-label={`Payment of expense ${number}`}>
        <span className="st-label">Has it been paid?</span>
        <div className="ex-seg">
          {[{ id: "paid", label: "Yes, paid" }, { id: "unpaid", label: "Not yet" }, { id: "partial", label: "Part paid" }].map((o) => (
            <button key={o.id} type="button" aria-pressed={entry.payment_status === o.id} onClick={() => set("payment_status")(o.id)}>{o.label}</button>
          ))}
        </div>
        {paid && (
          <div className="ex-grid ex-grid-main">
            <div>
              <span className="st-label">Paid by *</span>
              <div className="ex-catpick ex-catpick-sm" role="radiogroup" aria-label="Payment method">
                {meta.payment_methods.map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={entry.payment_method === m} onClick={() => set("payment_method")(m)}>{m}</button>
                ))}
              </div>
              {errors.payment_method && <p className="st-err">{errors.payment_method}</p>}
            </div>
            <F label="Paid on *" error={errors.payment_date}>
              {(id, err) => <input id={id} type="date" className="st-input" value={entry.payment_date} max={todayISO()} onChange={(e) => set("payment_date")(e.target.value)} aria-invalid={!!err} />}
            </F>
            {entry.payment_status === "partial" && (
              <F label="Amount paid (₹) *" error={errors.paid_amount}
                hint={int(entry.amount) > 0 && int(entry.paid_amount) > 0 ? `${money(Math.max(0, int(entry.amount) - int(entry.paid_amount)))} left to pay` : undefined}>
                {(id, err) => <input id={id} inputMode="numeric" className="st-input ex-mono" value={entry.paid_amount} onChange={(e) => set("paid_amount")(digits(e.target.value))} aria-invalid={!!err} />}
              </F>
            )}
          </div>
        )}
      </div>

      {/* everything else, folded away until wanted */}
      <details className="ex-more" open={moreOpen || undefined}>
        <summary><ChevronDown size={14} aria-hidden="true" />More details <small>bill no., GST, notes, photos of the bill{entry.files.length ? ` · ${entry.files.length} attached` : ""}</small></summary>
        <div className="ex-grid">
          <F label="Bill / reference no." error={errors.reference}>
            {(id) => <input id={id} className="st-input" value={entry.reference} maxLength={80} onChange={(e) => set("reference")(e.target.value)} />}
          </F>
          <F label="GST on the bill (₹)" error={errors.gst_amount} hint="As printed on the bill — leave empty if none">
            {(id, err) => <input id={id} inputMode="numeric" className="st-input ex-mono" value={entry.gst_amount} onChange={(e) => set("gst_amount")(digits(e.target.value))} placeholder="0" aria-invalid={!!err} />}
          </F>
          <div className="ex-check">
            <label>
              <input type="checkbox" checked={entry.gst_claimable} disabled={!(int(entry.gst_amount) > 0)} onChange={(e) => set("gst_claimable")(e.target.checked)} />
              <span>Input GST is claimable<small>Left out of Profit &amp; Loss</small></span>
            </label>
          </div>
          {paid && (
            <F label="Payment reference" hint="UTR / UPI / cheque no.">
              {(id) => <input id={id} className="st-input" value={entry.payment_reference} maxLength={80} onChange={(e) => set("payment_reference")(e.target.value)} />}
            </F>
          )}
          <F label="Notes" error={errors.description} wide>
            {(id) => <textarea id={id} className="st-input ex-textarea" value={entry.description} maxLength={1000} onChange={(e) => set("description")(e.target.value)} />}
          </F>
          <Attachments files={entry.files} onChange={set("files")} limits={meta.limits} error={errors.attachments} number={number} />
        </div>
      </details>
    </section>
  );
}

export default function ExpenseForm({ meta, stores, defaultStore, onClose, onSaved }) {
  const [entries, setEntries] = useState(() => [blankEntry(defaultStore)]);
  const [errors, setErrors] = useState({}); // uid -> {field: message}
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  // one key per form: a retry after a lost response can't save twice
  const key = useRef(newKey());
  const cards = useRef({});

  const total = useMemo(() => entries.reduce((s, e) => s + (int(e.amount) || 0), 0), [entries]);
  const files = entries.reduce((s, e) => s + e.files.length, 0);
  const limits = meta.limits;

  const update = (uid, next) => {
    setEntries((list) => list.map((e) => (e.uid === uid ? next : e)));
    if (errors[uid]) setErrors((m) => ({ ...m, [uid]: checkEntry(next, limits) }));
  };
  const add = (from) => {
    if (entries.length >= limits.max_entries) return setBanner(`Save at most ${limits.max_entries} expenses at a time.`);
    const next = from ? { ...from, uid: newUid(), files: [] } : blankEntry(defaultStore);
    setEntries((list) => {
      if (!from) return [...list, next];
      const at = list.findIndex((e) => e.uid === from.uid) + 1;
      return [...list.slice(0, at), next, ...list.slice(at)];
    });
    requestAnimationFrame(() => cards.current[next.uid]?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const remove = (uid) => {
    setEntries((list) => list.filter((e) => e.uid !== uid));
    setErrors(({ [uid]: _gone, ...rest }) => rest);
  };
  const jumpTo = (uid) => cards.current[uid]?.scrollIntoView({ behavior: "smooth", block: "start" });

  const save = async () => {
    const found = Object.fromEntries(entries.map((e) => [e.uid, checkEntry(e, limits)]).filter(([, v]) => Object.keys(v).length));
    if (files > limits.max_files_per_submission) return setBanner(`Attach at most ${limits.max_files_per_submission} files in one save.`);
    setErrors(found);
    const bad = entries.filter((e) => found[e.uid]);
    if (bad.length) {
      setBanner(`${bad.length === 1 ? "1 expense needs" : `${bad.length} expenses need`} attention: ${bad.map((e) => `#${entries.indexOf(e) + 1}`).join(", ")}. Nothing was saved.`);
      jumpTo(bad[0].uid);
      return;
    }
    const body = new FormData();
    body.append("submission_key", key.current);
    body.append("entries", JSON.stringify(entries.map(toPayload)));
    entries.forEach((e, i) => e.files.forEach((f) => body.append(`attachments_${i}`, f, f.name)));
    setBusy(true);
    setBanner("");
    try {
      const result = await api.upload("/expenses/bulk/", body);
      onSaved(result);
    } catch (err) {
      const rows = err.body?.entries;
      if (Array.isArray(rows)) {
        const mapped = {};
        rows.forEach((r) => { const e = entries[r.entry - 1]; if (e) mapped[e.uid] = flatten(r.errors); });
        setErrors(mapped);
        setBanner(err.body.detail || "Some expenses need attention. Nothing was saved.");
        const first = entries.find((e) => mapped[e.uid]);
        if (first) jumpTo(first.uid);
      } else {
        const fields = err.body && typeof err.body === "object" ? Object.values(flatten(err.body)).filter(Boolean) : [];
        setBanner(err.status === 403 ? "Your account isn't allowed to record expenses." : fields.join(" ") || err.message || "The expenses couldn't be saved. Check your connection and try again — nothing is saved twice.");
      }
    } finally {
      setBusy(false);
    }
  };

  // Escape / the close button never silently throw typed entries away. The
  // handler stays the same function so the dialog doesn't re-focus on each keystroke.
  const dirty = entries.some((e) => e.amount || e.category || e.vendor || e.reference || e.description || e.files.length);
  const closer = useRef(null);
  useEffect(() => {
    closer.current = () => {
      if (!dirty || window.confirm("Discard these expenses? Nothing has been saved yet.")) onClose();
    };
  });
  const requestClose = useCallback(() => closer.current?.(), []);

  const invalid = entries.filter((e) => errors[e.uid] && Object.keys(errors[e.uid]).length);
  return (
    <Dialog size="wide" title="Add expense" busy={busy} onClose={requestClose} labelledBy="ex-form-title"
      subtitle="Pick what it was for, the amount and whether it's paid. Add more expenses to save several bills at once."
      footer={(
        <div className="ex-foot">
          <p className="ex-foot-sum" aria-live="polite">
            <b>{entries.length}</b> {entries.length === 1 ? "expense" : "expenses"} · <b className="ex-mono">{money(total)}</b>
            {files > 0 && <> · {files} {files === 1 ? "file" : "files"}</>}
          </p>
          <div className="ex-foot-btns">
            <button type="button" className="st-btn" onClick={() => add()} disabled={busy}><Plus size={15} aria-hidden="true" />Add another expense</button>
            <button type="button" className="st-btn" data-variant="primary" onClick={save} disabled={busy}>
              <Save size={15} aria-hidden="true" />{busy ? "Saving…" : entries.length > 1 ? `Save ${entries.length} expenses` : "Save expense"}
            </button>
          </div>
        </div>
      )}>
      <div className="ex">
        {banner && <Alert>{banner}</Alert>}
        {entries.length > 3 && (
          <nav className="ex-jump" aria-label="Go to expense">
            {entries.map((e, i) => (
              <button key={e.uid} type="button" onClick={() => jumpTo(e.uid)} data-invalid={invalid.includes(e) || undefined}
                aria-label={`Go to expense ${i + 1}${invalid.includes(e) ? " (needs attention)" : ""}`}>{i + 1}</button>
            ))}
          </nav>
        )}
        {entries.map((e, i) => (
          <EntryCard key={e.uid} entry={e} number={i + 1} total={entries.length} errors={errors[e.uid] || {}} meta={meta} stores={stores}
            refEl={(el) => { cards.current[e.uid] = el; }}
            onChange={(next) => update(e.uid, next)} onRemove={() => remove(e.uid)} onDuplicate={() => add(e)} />
        ))}
        <button type="button" className="ex-add" onClick={() => add()} disabled={busy}><Plus size={16} aria-hidden="true" />Add another expense</button>
      </div>
    </Dialog>
  );
}
