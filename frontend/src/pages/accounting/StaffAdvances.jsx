import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, HandCoins, RefreshCw, Search, Users, Wallet } from "lucide-react";

import { api } from "../../lib/api";
import { fmt, money, todayISO } from "../../lib/theme";
import { toast } from "../../lib/toast";
import { Alert, Dialog, Field } from "../settings/StaffUi";
import "../settings/staff.css";
import "./expenses.css";

/*
 * Accounting -> Staff advances: every staff member, what they've been
 * advanced, what came back, and what they still owe (accounting.staff_advances).
 *   GET  /staff-advances/        the list
 *   GET  /staff-advances/<id>/   one person's entries
 *   POST /staff-advances/<id>/   give / paid back / adjust against salary
 */

const KINDS = {
  given: { label: "Give advance", verb: "Advance given", icon: ArrowUpRight, tone: "red", help: "Money paid to them now. It goes out of the cash / bank book and isn't an expense — they owe it back." },
  returned: { label: "Paid back", verb: "Paid back", icon: ArrowDownLeft, tone: "green", help: "They returned money. It comes into the cash / bank book." },
  salary: { label: "Cut from salary", verb: "Adjusted against salary", icon: Wallet, tone: "amber", help: "Kept back from their salary. Recorded as a Salary expense for this amount; nothing new goes through the cash / bank book (the cash left when the advance was given)." },
};
const digits = (v) => v.replace(/\D/g, "").slice(0, 9);
const errorText = (err) => {
  const body = err?.body && typeof err.body === "object" ? Object.values(err.body).flat().filter((v) => typeof v === "string") : [];
  return body.join(" ") || err?.message || "Something went wrong.";
};

function EntryForm({ person, kind, methods, onSaved, onCancel }) {
  const [form, setForm] = useState({ amount: kind === "given" ? "" : String(person.outstanding || ""), date: todayISO(), method: "Cash", reference: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: k === "amount" ? digits(e.target.value) : e.target.value }));
  const k = KINDS[kind];
  const save = async (e) => {
    e.preventDefault();
    if (!(Number(form.amount) > 0)) return setError("Enter the amount.");
    setBusy(true); setError("");
    try {
      const detail = await api.post(`/staff-advances/${person.id}/`, { kind, amount: Number(form.amount), date: form.date, method: kind === "salary" ? "" : form.method, reference: form.reference.trim(), note: form.note.trim() });
      toast.success(`${k.verb}: ${money(Number(form.amount))}`, `${person.name} now owes ${money(detail.staff.outstanding)}.`);
      onSaved(detail);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={save} className="sa-form" data-tone={k.tone}>
      <p className="sa-form-title"><k.icon size={15} aria-hidden="true" />{k.label}</p>
      <p className="st-help">{k.help}</p>
      <div className="ex-grid ex-grid-main">
        <Field id="sa-amount" label="Amount (₹) *" hint={kind !== "given" ? `Owes ${money(person.outstanding)}` : undefined}>
          <input id="sa-amount" inputMode="numeric" className="st-input ex-mono ex-amount" value={form.amount} onChange={set("amount")} placeholder="0" autoFocus />
        </Field>
        <Field id="sa-date" label="Date *">
          <input id="sa-date" type="date" className="st-input" value={form.date} max={todayISO()} onChange={set("date")} />
        </Field>
        {kind !== "salary" && (
          <div>
            <span className="st-label">{kind === "given" ? "Paid by *" : "Received by *"}</span>
            <div className="ex-catpick ex-catpick-sm" role="radiogroup" aria-label="Payment method">
              {methods.map((m) => <button key={m} type="button" role="radio" aria-checked={form.method === m} onClick={() => setForm((f) => ({ ...f, method: m }))}>{m}</button>)}
            </div>
          </div>
        )}
        {kind !== "salary" && form.method !== "Cash" && (
          <Field id="sa-ref" label="Reference" hint="UTR / UPI / cheque no.">
            <input id="sa-ref" className="st-input" value={form.reference} maxLength={80} onChange={set("reference")} />
          </Field>
        )}
        <Field id="sa-note" label="Note">
          <input id="sa-note" className="st-input" value={form.note} maxLength={200} onChange={set("note")} placeholder={kind === "salary" ? "e.g. November salary" : "e.g. Festival advance"} />
        </Field>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="ex-row-btns">
        <button type="button" className="st-btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="st-btn" data-variant="primary" disabled={busy}>{busy ? "Saving…" : `Save — ${form.amount ? money(Number(form.amount)) : "₹0"}`}</button>
      </div>
    </form>
  );
}

function PersonDialog({ person: initial, methods, startWith, onClose, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [kind, setKind] = useState(startWith || "");
  const person = detail?.staff || initial;

  useEffect(() => {
    api.get(`/staff-advances/${initial.id}/`).then(setDetail, (e) => setError(errorText(e)));
  }, [initial.id]);

  return (
    <Dialog size="wide" title={person.name} onClose={onClose} labelledBy="sa-person"
      subtitle={[person.role, person.store].filter(Boolean).join(" · ") || "Staff"}>
      <div className="ex">
        <div className="ex-totals">
          <div><span>Given</span><b className="ex-mono">{money(person.given)}</b></div>
          <div><span>Paid back</span><b className="ex-mono">{money(person.returned)}</b></div>
          <div><span>Cut from salary</span><b className="ex-mono">{money(person.salary)}</b></div>
          <div><span>Still owes</span><b className="ex-mono" data-tone={person.outstanding > 0 ? "red" : undefined}>{money(person.outstanding)}</b></div>
        </div>
        {kind ? (
          <EntryForm person={person} kind={kind} methods={methods} onCancel={() => setKind("")}
            onSaved={(d) => { setDetail(d); setKind(""); onChanged(); }} />
        ) : (
          <div className="ex-row-btns sa-actions">
            <button type="button" className="st-btn" data-variant="primary" onClick={() => setKind("given")}><HandCoins size={15} aria-hidden="true" />Give advance</button>
            <button type="button" className="st-btn" disabled={!(person.outstanding > 0)} onClick={() => setKind("returned")}><ArrowDownLeft size={15} aria-hidden="true" />Paid back</button>
            <button type="button" className="st-btn" disabled={!(person.outstanding > 0)} onClick={() => setKind("salary")}><Wallet size={15} aria-hidden="true" />Cut from salary</button>
          </div>
        )}
        <section>
          <h3 className="st-label">History</h3>
          {error ? <Alert>{error}</Alert> : !detail ? <span className="st-skel" style={{ height: 48, display: "block" }} /> : !detail.entries.length ? (
            <p className="st-note">No advances yet.</p>
          ) : (
            <ul className="sa-history">
              {detail.entries.map((e) => {
                const k = KINDS[e.kind];
                return (
                  <li key={e.id} data-tone={k.tone}>
                    <k.icon size={15} aria-hidden="true" />
                    <div className="min-w-0">
                      <b>{e.kind_label}</b>
                      <small>{fmt(e.date)}{e.method ? ` · ${e.method}` : ""}{e.reference ? ` · ${e.reference}` : ""}{e.expense_code ? ` · expense ${e.expense_code}` : ""}{e.store ? ` · ${e.store}` : ""} · by {e.by}</small>
                      {e.note && <small className="sa-note">{e.note}</small>}
                    </div>
                    <b className="ex-mono">{e.kind === "given" ? "+" : "−"}{money(e.amount)}</b>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </Dialog>
  );
}

export default function StaffAdvances() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [onlyOwing, setOnlyOwing] = useState(false);
  const [open, setOpen] = useState(null); // {person, startWith}
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api.get("/staff-advances/").then((d) => { setData(d); setError(""); }, (e) => setError(errorText(e)));
  }, [tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const close = useCallback(() => setOpen(null), []);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.staff || []).filter((r) => (!onlyOwing || r.outstanding > 0)
      && (!needle || [r.name, r.username, r.role, r.store, r.phone].some((v) => String(v || "").toLowerCase().includes(needle))));
  }, [data, q, onlyOwing]);

  if (error && !data) return <Alert>{error}</Alert>;
  return (
    <div className="st ex ex-page">
      <div className="st-head">
        <div>
          <h2 className="st-title">Staff advances</h2>
          <p className="st-desc">Money given to staff ahead of salary, and how it comes back — paid back, or cut from salary.</p>
        </div>
        <div className="ex-row-btns"><button type="button" className="st-btn" onClick={reload}><RefreshCw size={14} aria-hidden="true" />Refresh</button></div>
      </div>

      {data && (
        <div className="ex-totals">
          <div><span>Still owed to you</span><b className="ex-mono" data-tone={data.totals.outstanding > 0 ? "red" : undefined}>{money(data.totals.outstanding)}</b><small>{data.with_advance} {data.with_advance === 1 ? "person" : "people"}</small></div>
          <div><span>Given (all time)</span><b className="ex-mono">{money(data.totals.given)}</b></div>
          <div><span>Recovered</span><b className="ex-mono">{money(data.totals.recovered)}</b></div>
        </div>
      )}

      <div className="ex-bar-row">
        <label className="ex-search"><Search size={15} aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search staff by name, role or store" aria-label="Search staff" />
        </label>
        <div className="ex-chips ex-chips-sm" role="group" aria-label="Show">
          <button type="button" aria-pressed={!onlyOwing} onClick={() => setOnlyOwing(false)}>All staff</button>
          <button type="button" aria-pressed={onlyOwing} onClick={() => setOnlyOwing(true)}>Owes money</button>
        </div>
      </div>

      {!data ? (
        <div className="ex-list-skel">{[0, 1, 2].map((i) => <span key={i} className="st-skel" style={{ height: 52 }} />)}</div>
      ) : !rows.length ? (
        <div className="ex-empty"><Users size={22} aria-hidden="true" /><p>{onlyOwing ? "Nobody owes an advance right now." : "No staff found."}</p></div>
      ) : (
        <div className="ex-table sa-table" role="table" aria-label="Staff advances">
          <div className="ex-tr ex-th" role="row">
            {["Staff", "Store", "Given", "Recovered", "Still owes", ""].map((h, i) => <span key={h || i} role="columnheader">{h}</span>)}
          </div>
          {rows.map((r) => (
            <div key={r.id} className="ex-tr" role="row">
              <button type="button" role="cell" className="ex-td-main sa-name" onClick={() => setOpen({ person: r })} aria-label={`${r.name} — open advances`}>
                <b>{r.name}</b><small>{r.role || r.username}{r.last_entry ? ` · last ${fmt(r.last_entry)}` : ""}</small>
              </button>
              <span role="cell" data-label="Store" data-empty={!r.store || undefined}>{r.store || "—"}</span>
              <span role="cell" data-label="Given" className="ex-mono ex-r">{r.given ? money(r.given) : "—"}</span>
              <span role="cell" data-label="Recovered" className="ex-mono ex-r">{r.recovered ? money(r.recovered) : "—"}</span>
              <span role="cell" data-label="Still owes" className="ex-mono ex-r">{r.outstanding > 0 ? <b className="sa-owes">{money(r.outstanding)}</b> : <span className="sa-clear">Clear</span>}</span>
              <span role="cell" className="sa-row-btns">
                <button type="button" className="st-btn" onClick={() => setOpen({ person: r, startWith: "given" })}><HandCoins size={14} aria-hidden="true" />Advance</button>
                <button type="button" className="st-btn" onClick={() => setOpen({ person: r })}>Details</button>
              </span>
            </div>
          ))}
        </div>
      )}

      {open && data && <PersonDialog person={open.person} startWith={open.startWith} methods={data.methods} onClose={close} onChanged={reload} />}
    </div>
  );
}
