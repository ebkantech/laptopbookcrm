import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ArrowDownUp, Ban, ChevronLeft, ChevronRight, Download, Eye, FileText, History, ImageIcon, Paperclip, Pencil,
  Plus, ReceiptText, RefreshCw, Search, SlidersHorizontal, Wallet, X,
} from "lucide-react";
import { api } from "../../lib/api";
import { fmt, money, todayISO } from "../../lib/theme";
import { useSession } from "../../context/SessionContext";
import { Alert, Dialog, Field } from "../settings/StaffUi";
import ExpenseForm, { StorePicker } from "./ExpenseForm";
import { fileSize } from "./format";
import { PERIODS, periodRange } from "./period";
import "../settings/staff.css";
import "./expenses.css";

/*
 * Accounting -> Expenses. Shown only to accounts the API marks
 * can_manage_expenses (Superuser, authorised Admin / Accounts); every
 * endpoint below refuses anyone else with 403 and scopes records to the
 * account's store (accounting.expense_views).
 *   GET  /expenses/meta/  /expenses/?filters  /expenses/<id>/
 *   POST /expenses/bulk/  /expenses/<id>/payments/  /cancel/  /attachments/
 *   PATCH /expenses/<id>/   DELETE /expenses/<id>/attachments/<a>/
 *   GET  /expense-attachments/<a>/file/[?download=1]
 */

const STATUS = { unpaid: "Unpaid", partial: "Partly paid", paid: "Paid" };
const STATUS_TONE = { unpaid: "red", partial: "amber", paid: "green" };
const SORTS = [
  { id: "-date", label: "Newest first" }, { id: "date", label: "Oldest first" },
  { id: "-amount", label: "Highest amount" }, { id: "amount", label: "Lowest amount" }, { id: "-id", label: "Latest ID" },
];
const EMPTY_FILTERS = { q: "", store: "", category: "", payment_status: "", date_from: "", date_to: "", vendor: "", state: "active", sort: "-date" };
const PAY_CHIPS = [{ id: "", label: "All" }, { id: "unpaid", label: "To pay" }, { id: "partial", label: "Part paid" }, { id: "paid", label: "Paid" }];

const storeName = (e) => e.store?.name || "Shared / head office";
const errorText = (err) => {
  if (!err) return "";
  const body = err.body && typeof err.body === "object" ? Object.values(err.body).flat().filter((v) => typeof v === "string") : [];
  return body.join(" ") || err.message || "Something went wrong.";
};

function Tag({ tone = "grey", children }) {
  return <span className="ex-tag" data-tone={tone}>{children}</span>;
}

function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// a dialog handler that keeps one identity (StaffUi.Dialog re-focuses when it changes)
function useStable(fn) {
  const ref = useRef(fn);
  useEffect(() => { ref.current = fn; });
  return useCallback((...args) => ref.current(...args), []);
}

/* ---------------------------------------------------------------- *
 * Attachments: preview / download through the authorised endpoint
 * ---------------------------------------------------------------- */

async function download(att) {
  const url = await api.blobUrl(`/expense-attachments/${att.id}/file/?download=1`);
  const a = document.createElement("a");
  a.href = url;
  a.download = att.original_name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function Viewer({ att, onClose }) {
  const [state, setState] = useState({ url: null, error: null });
  useEffect(() => {
    let url = null;
    let live = true;
    api.blobUrl(`/expense-attachments/${att.id}/file/`).then(
      (u) => { url = u; if (live) setState({ url: u, error: null }); else URL.revokeObjectURL(u); },
      (error) => live && setState({ url: null, error }),
    );
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [att.id]);
  const close = useStable(onClose);
  return (
    <Dialog size="wide" title={att.original_name} subtitle={`${att.kind === "pdf" ? "PDF" : "Image"} · ${fileSize(att.size)}`} onClose={close}
      labelledBy="ex-viewer-title"
      footer={<button type="button" className="st-btn" onClick={() => download(att)}><Download size={15} aria-hidden="true" />Download</button>}>
      <div className="ex-viewer">
        {state.error ? <Alert>The file couldn't be loaded.</Alert> : !state.url ? <p className="st-note">Loading…</p>
          : att.kind === "pdf" ? <iframe title={att.original_name} src={state.url} />
            : <img src={state.url} alt={att.original_name} />}
      </div>
    </Dialog>
  );
}

function AttachmentList({ expense, onChanged, canEdit }) {
  const [viewing, setViewing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);
  const add = async (files) => {
    if (!files.length) return;
    const body = new FormData();
    [...files].forEach((f) => body.append("attachments", f, f.name));
    setBusy(true); setError("");
    try { onChanged(await api.upload(`/expenses/${expense.id}/attachments/`, body)); } catch (e) { setError(errorText(e)); }
    setBusy(false);
    if (input.current) input.current.value = "";
  };
  const remove = async (att) => {
    if (!window.confirm(`Remove ${att.original_name} from ${expense.code}? This can't be undone.`)) return;
    setBusy(true); setError("");
    try { onChanged(await api.del(`/expenses/${expense.id}/attachments/${att.id}/`)); } catch (e) { setError(errorText(e)); }
    setBusy(false);
  };
  return (
    <section className="ex-sec" aria-label="Attachments">
      <div className="ex-sec-head">
        <h3 className="ex-sec-title"><Paperclip size={14} aria-hidden="true" />Attachments ({expense.attachments.length})</h3>
        {canEdit && (
          <>
            <button type="button" className="st-btn" onClick={() => input.current?.click()} disabled={busy}><Plus size={14} aria-hidden="true" />Add files</button>
            <input ref={input} type="file" multiple hidden accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
              aria-label="Add attachments" onChange={(e) => add(e.target.files)} />
          </>
        )}
      </div>
      {error && <Alert>{error}</Alert>}
      {expense.attachments.length ? (
        <ul className="ex-file-list">
          {expense.attachments.map((a) => (
            <li key={a.id}>
              {a.kind === "pdf" ? <FileText size={15} aria-hidden="true" /> : <ImageIcon size={15} aria-hidden="true" />}
              <span className="ex-file-name" title={a.original_name}>{a.original_name}</span>
              <span className="ex-file-size">{fileSize(a.size)}</span>
              <button type="button" className="st-icon-btn" onClick={() => setViewing(a)} aria-label={`Preview ${a.original_name}`}><Eye size={14} aria-hidden="true" /></button>
              <button type="button" className="st-icon-btn" onClick={() => download(a)} aria-label={`Download ${a.original_name}`}><Download size={14} aria-hidden="true" /></button>
              {canEdit && <button type="button" className="st-icon-btn" onClick={() => remove(a)} disabled={busy} aria-label={`Remove ${a.original_name}`}><X size={14} aria-hidden="true" /></button>}
            </li>
          ))}
        </ul>
      ) : <p className="st-note">No attachments.</p>}
      {viewing && <Viewer att={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}

/* ---------------------------------------------------------------- *
 * Details: edit, record payment, cancel
 * ---------------------------------------------------------------- */

function TextField({ label, value, onChange, error, ...rest }) {
  const id = useId();
  return <Field id={id} label={label} error={error}><input id={id} className="st-input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} {...rest} /></Field>;
}

function EditForm({ expense, meta, stores, onSaved, onCancel }) {
  const [v, setV] = useState({
    store: expense.store ? String(expense.store.id) : "shared", category: String(expense.category), expense_date: expense.expense_date,
    amount: String(expense.amount), gst_amount: expense.gst_amount ? String(expense.gst_amount) : "", gst_claimable: expense.gst_claimable,
    vendor: expense.vendor, reference: expense.reference, description: expense.description,
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (val) => setV((s) => ({ ...s, [k]: val }));
  const num = (s) => s.replace(/\D/g, "").slice(0, 10);
  const storeId = useId();
  const catId = useId();
  const save = async () => {
    setBusy(true); setErrors({});
    const shared = v.store === "shared";
    try {
      onSaved(await api.patch(`/expenses/${expense.id}/`, {
        stock_point: shared ? null : Number(v.store), shared, category: Number(v.category), expense_date: v.expense_date,
        amount: Number(v.amount), gst_amount: Number(v.gst_amount || 0), gst_claimable: v.gst_claimable && Number(v.gst_amount) > 0,
        vendor: v.vendor, reference: v.reference, description: v.description,
      }));
    } catch (e) {
      const out = {};
      Object.entries(e.body || {}).forEach(([k, m]) => { out[k] = [].concat(m).join(" "); });
      setErrors(Object.keys(out).length ? out : { detail: errorText(e) });
    }
    setBusy(false);
  };
  return (
    <section className="ex-sec" aria-label="Edit expense">
      {(errors.detail || errors.non_field_errors) && <Alert>{errors.detail || errors.non_field_errors}</Alert>}
      {expense.payments.length > 0 && <p className="st-note">Payments already recorded stay as they are. The amount can't go below {money(expense.paid_amount)}, and the store can't change.</p>}
      <div className="ex-grid">
        <Field id={storeId} label="Store" error={errors.stock_point}>
          <StorePicker id={storeId} value={v.store} onChange={set("store")} stores={stores} canShared={meta.can_record_shared} error={errors.stock_point} />
        </Field>
        <Field id={catId} label="Category" error={errors.category}>
          <select id={catId} className="st-input" value={v.category} onChange={(e) => set("category")(e.target.value)}>
            {meta.categories.filter((c) => c.is_active || String(c.id) === v.category).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </Field>
        <TextField label="Expense date" type="date" max={todayISO()} value={v.expense_date} onChange={set("expense_date")} error={errors.expense_date} />
        <TextField label="Amount (₹)" inputMode="numeric" className="st-input ex-mono" value={v.amount} onChange={(x) => set("amount")(num(x))} error={errors.amount} />
        <TextField label="Paid to / vendor" maxLength={120} value={v.vendor} onChange={set("vendor")} error={errors.vendor} />
        <TextField label="Bill / reference no." maxLength={80} value={v.reference} onChange={set("reference")} error={errors.reference} />
        <TextField label="GST on the bill (₹)" inputMode="numeric" value={v.gst_amount} onChange={(x) => set("gst_amount")(num(x))} error={errors.gst_amount} />
        <div className="ex-check"><label><input type="checkbox" checked={v.gst_claimable} disabled={!(Number(v.gst_amount) > 0)} onChange={(e) => set("gst_claimable")(e.target.checked)} />
          <span>Input GST is claimable<small>Left out of Profit &amp; Loss</small></span></label></div>
        <div className="ex-span"><TextField label="Description / notes" maxLength={1000} value={v.description} onChange={set("description")} /></div>
      </div>
      <div className="ex-row-btns">
        <button type="button" className="st-btn" onClick={onCancel} disabled={busy}>Discard changes</button>
        <button type="button" className="st-btn" data-variant="primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save changes"}</button>
      </div>
    </section>
  );
}

function PaymentForm({ expense, methods, onSaved }) {
  const [v, setV] = useState({ amount: String(expense.outstanding), payment_method: "", payment_date: todayISO(), reference: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const methodId = useId();
  const save = async () => {
    setBusy(true); setError("");
    try { onSaved(await api.post(`/expenses/${expense.id}/payments/`, { ...v, amount: Number(v.amount) })); } catch (e) { setError(errorText(e)); }
    setBusy(false);
  };
  return (
    <div className="ex-pay-form">
      {error && <Alert>{error}</Alert>}
      <div className="ex-grid">
        <TextField label={`Amount (₹) · ${money(expense.outstanding)} outstanding`} inputMode="numeric" value={v.amount} onChange={(x) => setV((s) => ({ ...s, amount: x.replace(/\D/g, "") }))} />
        <Field id={methodId} label="Payment method">
          <select id={methodId} className="st-input" value={v.payment_method} onChange={(e) => setV((s) => ({ ...s, payment_method: e.target.value }))}>
            <option value="">Choose…</option>
            {methods.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </Field>
        <TextField label="Payment date" type="date" max={todayISO()} value={v.payment_date} onChange={(x) => setV((s) => ({ ...s, payment_date: x }))} />
        <TextField label="Payment reference" maxLength={80} value={v.reference} onChange={(x) => setV((s) => ({ ...s, reference: x }))} />
      </div>
      <div className="ex-row-btns">
        <button type="button" className="st-btn" data-variant="primary" onClick={save} disabled={busy || !v.payment_method || !(Number(v.amount) > 0)}>
          <Wallet size={14} aria-hidden="true" />{busy ? "Recording…" : "Record payment"}
        </button>
      </div>
    </div>
  );
}

function CancelForm({ expense, onSaved, onBack }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const live = expense.payments.filter((p) => !p.reversed_at);
  const save = async () => {
    setBusy(true); setError("");
    try { onSaved(await api.post(`/expenses/${expense.id}/cancel/`, { reason })); } catch (e) { setError(errorText(e)); }
    setBusy(false);
  };
  return (
    <section className="ex-sec ex-danger" aria-label="Cancel expense">
      <h3 className="ex-sec-title"><Ban size={14} aria-hidden="true" />Cancel {expense.code}?</h3>
      <p className="st-note">It leaves Profit &amp; Loss and can't be edited afterwards. Nothing is deleted.
        {live.length > 0 && ` ${live.length === 1 ? "Its payment" : `Its ${live.length} payments`} (${money(live.reduce((s, p) => s + p.amount, 0))}) will get a reversing entry in the cash / bank book dated today; the original entries stay as they are.`}</p>
      {error && <Alert>{error}</Alert>}
      <TextField label="Reason *" maxLength={200} value={reason} onChange={setReason} autoFocus />
      <div className="ex-row-btns">
        <button type="button" className="st-btn" onClick={onBack} disabled={busy}>Keep expense</button>
        <button type="button" className="st-btn" data-variant="danger" onClick={save} disabled={busy || !reason.trim()}>{busy ? "Cancelling…" : "Cancel expense"}</button>
      </div>
    </section>
  );
}

function Detail({ id, meta, stores, onClose, onChanged }) {
  const [expense, setExpense] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("view"); // view | edit | pay | cancel
  useEffect(() => {
    let live = true;
    api.get(`/expenses/${id}/`).then((d) => live && setExpense(d), (e) => live && setError(e));
    return () => { live = false; };
  }, [id]);
  const changed = (next) => { setExpense(next); setMode("view"); onChanged(); };
  const close = useStable(onClose);
  const active = expense?.status === "active";

  return (
    <Dialog size="wide" title={expense ? `${expense.code} · ${expense.category_label}` : "Expense"} onClose={close} labelledBy="ex-detail-title"
      subtitle={expense && <span className="ex-detail-sub">{storeName(expense)} · {fmt(expense.expense_date)} {expense.status === "cancelled" ? <Tag tone="grey">Cancelled</Tag> : <Tag tone={STATUS_TONE[expense.payment_status]}>{STATUS[expense.payment_status]}</Tag>}</span>}
      footer={expense && active && mode === "view" && (
        <div className="ex-row-btns">
          <button type="button" className="st-btn" onClick={() => setMode("cancel")}><Ban size={14} aria-hidden="true" />Cancel expense</button>
          <button type="button" className="st-btn" onClick={() => setMode("edit")}><Pencil size={14} aria-hidden="true" />Edit</button>
          {expense.outstanding > 0 && <button type="button" className="st-btn" data-variant="primary" onClick={() => setMode("pay")}><Wallet size={14} aria-hidden="true" />Record payment</button>}
        </div>
      )}>
      <div className="ex">
        {error ? <Alert>{error.status === 404 ? "This expense doesn't exist or isn't at your store." : errorText(error)}</Alert>
          : !expense ? <p className="st-note">Loading…</p> : (
            <>
              {expense.status === "cancelled" && (
                <Alert tone="info">Cancelled {expense.cancelled_at ? fmt(expense.cancelled_at.slice(0, 10)) : ""} by {expense.cancelled_by_name || "—"}: {expense.cancel_reason}</Alert>
              )}
              {mode === "edit" ? <EditForm expense={expense} meta={meta} stores={stores} onSaved={changed} onCancel={() => setMode("view")} />
                : mode === "cancel" ? <CancelForm expense={expense} onSaved={changed} onBack={() => setMode("view")} /> : (
                  <dl className="ex-kv">
                    <div><dt>Amount</dt><dd className="ex-mono ex-big">{money(expense.amount)}</dd></div>
                    <div><dt>Paid</dt><dd className="ex-mono">{money(expense.paid_amount)}</dd></div>
                    <div><dt>Outstanding</dt><dd className="ex-mono">{money(expense.outstanding)}</dd></div>
                    <div><dt>Counted in P&amp;L</dt><dd className="ex-mono">{expense.status === "active" ? money(expense.recognised_amount) : "—"}</dd></div>
                    <div><dt>Store</dt><dd>{storeName(expense)}</dd></div>
                    <div><dt>Category</dt><dd>{expense.category_label} <small>({expense.classification === "other" ? "other expense" : "operating"})</small></dd></div>
                    <div><dt>Expense date</dt><dd>{fmt(expense.expense_date)}</dd></div>
                    <div><dt>Paid to / vendor</dt><dd data-empty={!expense.vendor}>{expense.vendor || "Not given"}</dd></div>
                    <div><dt>Bill / reference</dt><dd data-empty={!expense.reference}>{expense.reference || "Not given"}</dd></div>
                    <div><dt>GST on bill</dt><dd>{expense.gst_amount ? `${money(expense.gst_amount)}${expense.gst_claimable ? " · claimable" : " · not claimable"}` : "None"}</dd></div>
                    <div className="ex-span"><dt>Description</dt><dd data-empty={!expense.description}>{expense.description || "No notes"}</dd></div>
                    <div><dt>Created</dt><dd>{expense.created_by_name} · {fmt(expense.created_at.slice(0, 10))}</dd></div>
                    <div><dt>Last updated</dt><dd>{expense.updated_by_name || "—"} · {fmt(expense.updated_at.slice(0, 10))}</dd></div>
                  </dl>
                )}

              <section className="ex-sec" aria-label="Payments">
                <h3 className="ex-sec-title"><Wallet size={14} aria-hidden="true" />Payments</h3>
                {mode === "pay" && <PaymentForm expense={expense} methods={meta.payment_methods} onSaved={changed} />}
                {expense.payments.length ? (
                  <ul className="ex-list">
                    {expense.payments.map((p) => (
                      <li key={p.id}>
                        <span><b className="ex-mono">{money(p.amount)}</b> · {p.method} · {fmt(p.paid_on)}{p.reference && <> · <span className="ex-mono">{p.reference}</span></>}</span>
                        <span className="st-note">{p.book === "cash" ? "Cash book" : "Bank book"} · {p.by_name}{p.reversed_at && <> · <Tag tone="grey">Reversed</Tag></>}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="st-note">No payment recorded — nothing has been posted to the cash or bank book.</p>}
              </section>

              <AttachmentList expense={expense} canEdit={active} onChanged={changed} />

              <section className="ex-sec" aria-label="History">
                <h3 className="ex-sec-title"><History size={14} aria-hidden="true" />History</h3>
                {expense.history.length ? (
                  <ul className="ex-list">
                    {expense.history.map((h, i) => (
                      <li key={i}><span>{h.description}</span><span className="st-note">{h.by} · {new Date(h.at).toLocaleString("en-IN")}</span></li>
                    ))}
                  </ul>
                ) : <p className="st-note">No recorded changes.</p>}
              </section>
            </>
          )}
      </div>
    </Dialog>
  );
}

/* ---------------------------------------------------------------- *
 * List
 * ---------------------------------------------------------------- */

export default function Expenses() {
  const { me } = useSession();
  const [meta, setMeta] = useState(null);
  const [stores, setStores] = useState([]);
  const [setupError, setSetupError] = useState(null);
  const [period, setPeriod] = useState("month");
  const [filters, setFilters] = useState(() => ({ ...EMPTY_FILTERS, ...periodRange("month", todayISO()) }));
  const [more, setMore] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [tick, setTick] = useState(0);
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [flash, setFlash] = useState("");
  const q = useDebounced(filters.q);
  const vendor = useDebounced(filters.vendor);

  useEffect(() => {
    Promise.all([api.get("/expenses/meta/"), api.getAll("/stock-points/")])
      .then(([m, s]) => { setMeta(m); setStores(s); }, setSetupError);
  }, []);

  const params = new URLSearchParams(Object.entries({ ...filters, q, vendor, page: String(page) }).filter(([, v]) => v));
  const qs = params.toString();
  useEffect(() => {
    let live = true;
    api.get(`/expenses/?${qs}`).then((d) => { if (live) { setData(d); setLoadError(null); } }, (e) => live && setLoadError(e));
    return () => { live = false; };
  }, [qs, tick]);

  useEffect(() => {
    if (!flash) return undefined;
    const t = setTimeout(() => setFlash(""), 7000);
    return () => clearTimeout(t);
  }, [flash]);

  const setF = (k) => (v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };
  const reload = () => setTick((t) => t + 1);
  const pages = data ? Math.max(1, Math.ceil(data.count / 50)) : 1;
  const filtered = Object.entries(filters).some(([k, v]) => v !== EMPTY_FILTERS[k] && !(k in periodRange("month", todayISO()) && period !== "custom"));
  const pickPeriod = (id) => {
    setPeriod(id);
    if (id !== "custom") { setFilters((f) => ({ ...f, ...periodRange(id, todayISO()) })); setPage(1); }
  };
  const moreCount = ["store", "vendor", "sort"].filter((k) => filters[k] !== EMPTY_FILTERS[k]).length + (filters.state !== "active" ? 1 : 0);
  const clearAll = () => { setFilters({ ...EMPTY_FILTERS, ...periodRange("month", todayISO()) }); setPeriod("month"); setPage(1); };
  const periodLabel = period === "custom"
    ? (filters.date_from || filters.date_to ? `${filters.date_from ? fmt(filters.date_from) : "…"} – ${filters.date_to ? fmt(filters.date_to) : "today"}` : "All dates")
    : PERIODS.find((x) => x.id === period)?.label;

  if (setupError) return <Alert>{setupError.status === 403 ? "Your role doesn't include expense management." : errorText(setupError)}</Alert>;

  return (
    <div className="st ex ex-page">
      <div className="st-head">
        <div>
          <h2 className="st-title">Expenses</h2>
          <p className="st-desc">Shop and head-office costs — rent, bills, salaries, supplies. They count in Profit &amp; Loss on the expense date; payments go to the cash or bank book.</p>
        </div>
        <div className="ex-row-btns">
          <button type="button" className="st-btn" onClick={reload}><RefreshCw size={14} aria-hidden="true" />Refresh</button>
          <button type="button" className="st-btn" data-variant="primary" onClick={() => setAdding(true)} disabled={!meta}><Plus size={15} aria-hidden="true" />Add expense</button>
        </div>
      </div>
      {flash && <Alert tone="ok">{flash}</Alert>}

      <div className="ex-bar" role="search">
        <div className="ex-chips" role="group" aria-label="Period">
          {PERIODS.map((p) => <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => pickPeriod(p.id)}>{p.label}</button>)}
        </div>
        {period === "custom" && (
          <div className="ex-custom">
            <label className="ex-date"><span>From</span><input type="date" className="st-input" value={filters.date_from} max={filters.date_to || undefined} onChange={(e) => setF("date_from")(e.target.value)} /></label>
            <label className="ex-date"><span>To</span><input type="date" className="st-input" value={filters.date_to} min={filters.date_from || undefined} onChange={(e) => setF("date_to")(e.target.value)} /></label>
          </div>
        )}
        <div className="ex-bar-row">
          <label className="ex-search"><Search size={15} aria-hidden="true" />
            <input value={filters.q} onChange={(e) => setF("q")(e.target.value)} placeholder="Search expense ID or bill no." aria-label="Search by expense ID or reference" />
          </label>
          <select className="st-input" value={filters.category} onChange={(e) => setF("category")(e.target.value)} aria-label="Category">
            <option value="">All categories</option>
            {meta?.categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <div className="ex-chips ex-chips-sm" role="group" aria-label="Payment">
            {PAY_CHIPS.map((c) => <button key={c.id || "all"} type="button" aria-pressed={filters.payment_status === c.id} onClick={() => setF("payment_status")(c.id)}>{c.label}</button>)}
          </div>
          <button type="button" className="st-btn" aria-expanded={more} onClick={() => setMore((v) => !v)}>
            <SlidersHorizontal size={14} aria-hidden="true" />More{moreCount ? ` (${moreCount})` : ""}
          </button>
          {filtered && <button type="button" className="st-btn" onClick={clearAll}>Clear</button>}
        </div>
        {more && (
          <div className="ex-filters">
            <select className="st-input" value={filters.store} onChange={(e) => setF("store")(e.target.value)} aria-label="Store">
              <option value="">All stores</option>
              {stores.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
              {meta?.can_record_shared && <option value="shared">Shared / head office</option>}
            </select>
            <input className="st-input" value={filters.vendor} onChange={(e) => setF("vendor")(e.target.value)} placeholder="Paid to / vendor" aria-label="Vendor" />
            <select className="st-input" value={filters.state} onChange={(e) => setF("state")(e.target.value)} aria-label="Show">
              <option value="active">Active</option><option value="cancelled">Cancelled</option><option value="all">Active and cancelled</option>
            </select>
            <label className="ex-sort"><ArrowDownUp size={14} aria-hidden="true" />
              <select value={filters.sort} onChange={(e) => setF("sort")(e.target.value)} aria-label="Sort">
                {SORTS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
          </div>
        )}
      </div>

      {data && (
        <div className="ex-summary" aria-live="polite">
          <div className="ex-totals">
            <div><span>Spent · {periodLabel}</span><b className="ex-mono">{money(data.totals.amount)}</b><small>{data.totals.count} {data.totals.count === 1 ? "expense" : "expenses"}</small></div>
            <div><span>Paid</span><b className="ex-mono">{money(data.totals.paid)}</b></div>
            <div><span>Still to pay</span><b className="ex-mono" data-tone={data.totals.outstanding > 0 ? "red" : undefined}>{money(data.totals.outstanding)}</b>
              {data.totals.outstanding > 0 && filters.payment_status !== "unpaid" && <button type="button" className="ex-link" onClick={() => setF("payment_status")("unpaid")}>Show unpaid</button>}</div>
          </div>
          {data.totals.by_category?.length > 0 && data.totals.amount > 0 && (
            <div className="ex-cats" aria-label="Spending by category">
              <span className="st-label">Where it went</span>
              {data.totals.by_category.slice(0, 6).map((c) => (
                <button key={c.id} type="button" className="ex-cat" aria-pressed={String(filters.category) === String(c.id)}
                  onClick={() => setF("category")(String(filters.category) === String(c.id) ? "" : String(c.id))}>
                  <span className="ex-cat-name">{c.label}</span>
                  <span className="ex-cat-bar"><i style={{ width: `${Math.max(3, Math.round((c.amount / data.totals.by_category[0].amount) * 100))}%` }} /></span>
                  <b className="ex-mono">{money(c.amount)}</b>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {loadError ? <Alert>{errorText(loadError)}</Alert> : !data ? (
        <div className="ex-list-skel">{[0, 1, 2, 3].map((i) => <span key={i} className="st-skel" style={{ height: 52 }} />)}</div>
      ) : !data.results.length ? (
        <div className="ex-empty"><ReceiptText size={22} aria-hidden="true" /><p>{filtered ? "No expenses match these filters." : `No expenses for ${periodLabel?.toLowerCase()}.`}</p>
          {!filtered && meta && <button type="button" className="st-btn" data-variant="primary" onClick={() => setAdding(true)}><Plus size={15} aria-hidden="true" />Add expense</button>}
        </div>
      ) : (
        <div className="ex-table" role="table" aria-label="Expenses">
          <div className="ex-tr ex-th" role="row">
            {["Date", "Category", "Paid to", "Store", "Amount", "Payment"].map((h) => <span key={h} role="columnheader">{h}</span>)}
          </div>
          {data.results.map((e) => (
            <button key={e.id} type="button" className="ex-tr" role="row" onClick={() => setOpenId(e.id)} data-cancelled={e.status === "cancelled" || undefined}
              aria-label={`${e.code}, ${money(e.amount)}, ${storeName(e)} — open details`}>
              <span role="cell" className="ex-td-main"><b>{fmt(e.expense_date)}</b><small>{e.code}</small></span>
              <span role="cell" data-label="Category"><b className="ex-cell-strong">{e.category_label}</b>{e.attachment_count > 0 && <small className="ex-clip" title={`${e.attachment_count} file(s)`}><Paperclip size={11} aria-hidden="true" />{e.attachment_count}</small>}</span>
              <span role="cell" data-label="Paid to" data-empty={!e.vendor || undefined}>{e.vendor || "—"}{e.reference && <small className="ex-sub">Bill {e.reference}</small>}</span>
              <span role="cell" data-label="Store">{storeName(e)}</span>
              <span role="cell" data-label="Amount" className="ex-mono ex-r">{money(e.amount)}</span>
              <span role="cell" data-label="Payment">{e.status === "cancelled" ? <Tag>Cancelled</Tag> : <Tag tone={STATUS_TONE[e.payment_status]}>{STATUS[e.payment_status]}</Tag>}{e.payment_method && e.status !== "cancelled" && <small className="ex-sub">{e.payment_method}</small>}</span>
            </button>
          ))}
        </div>
      )}
      {data && pages > 1 && (
        <div className="ex-pager">
          <button type="button" className="st-icon-btn" onClick={() => setPage((p) => p - 1)} disabled={!data.previous} aria-label="Previous page"><ChevronLeft size={16} /></button>
          <span className="st-note">Page {page} of {pages}</span>
          <button type="button" className="st-icon-btn" onClick={() => setPage((p) => p + 1)} disabled={!data.next} aria-label="Next page"><ChevronRight size={16} /></button>
        </div>
      )}

      {adding && meta && (
        <ExpenseForm meta={meta} stores={stores} defaultStore={me?.sees_all_stores ? "" : me?.stock_point}
          onClose={() => setAdding(false)}
          onSaved={(r) => {
            setAdding(false);
            setFlash(r.duplicate ? "These expenses were already saved — nothing was added twice." : `Saved ${r.count} ${r.count === 1 ? "expense" : "expenses"} · ${money(r.total)}.`);
            reload();
          }} />
      )}
      {openId && meta && <Detail id={openId} meta={meta} stores={stores} onClose={() => setOpenId(null)} onChanged={reload} />}
      {!meta && !setupError && <p className="st-note">Loading categories…</p>}
    </div>
  );
}
