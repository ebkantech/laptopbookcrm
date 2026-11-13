import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Check, FileText, Mail, MessageSquare, RotateCcw, Search } from "lucide-react";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";
import { ErrorNote, Eyebrow, Pill, PillButton, Spinner } from "../../components/Atoms";
import { filterMessages, insertAt, previewText, textProblems } from "./brandingText";

/*
 * Settings -> Business & messages: everything the customer sees that isn't
 * a record -- the business details printed on invoices, statements and the
 * rental agreement, the invoice footer / signatory / notes, the agreement's
 * conditions, and the wording of every WhatsApp / SMS / email the CRM sends.
 * Anyone may look; only the Owner / an Admin may change it (the API enforces it).
 */

const label = { fontFamily: F.body, color: C.inkSoft };
const input = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}`, borderRadius: 8 };
const CHANNEL = { whatsapp: "WhatsApp", sms: "SMS", email: "Email" };

function Panel({ icon: Icon, title, note, children }) {
  return (
    <section data-panel className="p-5" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, borderRadius: 14 }}>
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center" style={{ borderRadius: 999, backgroundColor: `color-mix(in srgb, ${C.stamp} 7%, transparent)` }}>
          <Icon size={17} style={{ color: C.stamp }} />
        </span>
        <div className="min-w-0">
          <p style={{ fontFamily: F.display, fontWeight: 700, color: C.ink, fontSize: 16 }}>{title}</p>
          {note && <p className="mt-0.5 text-xs" style={label}>{note}</p>}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Field({ name, title, hint, value, onChange, disabled, area, rows = 3, placeholder, mono }) {
  const common = {
    value: value ?? "", disabled, placeholder, onChange: (e) => onChange(name, e.target.value),
    className: "mt-1 block w-full px-2.5 py-2 text-sm outline-none",
    style: { ...input, fontFamily: mono ? F.mono : F.body, opacity: disabled ? 0.75 : 1 },
  };
  return (
    <label className="block text-xs" style={label}>
      {title}
      {area ? <textarea rows={rows} {...common} /> : <input {...common} />}
      {hint && <span className="mt-1 block text-[11px]" style={label}>{hint}</span>}
    </label>
  );
}

function BusinessForm({ data, onSaved }) {
  const [form, setForm] = useState(data.business);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const set = (k, v) => { setForm((f) => ({ ...f, [k]: v })); setSaved(""); };
  const eff = data.effective;
  const dirty = Object.keys(form).some((k) => (form[k] ?? "") !== (data.business[k] ?? ""));

  const save = async (fields, what) => {
    setBusy(true); setError(""); setSaved("");
    try {
      const body = Object.fromEntries(fields.map((k) => [k, form[k] ?? ""]));
      const fresh = await api.patch("/branding/business/", body);
      setForm(fresh.business);  // as the server stored it (GSTIN upper-cased, blank lines dropped)
      onSaved(fresh);
      setSaved(what);
    } catch (e) {
      const b = e.body || {};
      setError(Object.entries(b).map(([k, v]) => `${k === "detail" ? "" : `${k.replace("_", " ")}: `}${[].concat(v).join(" ")}`).join(" ") || e.message);
    } finally {
      setBusy(false);
    }
  };
  const ro = !data.can_edit;
  const BIZ = ["name", "address", "phone", "email", "gstin", "website"];
  const DOCS = ["invoice_footer", "signatory_label", "invoice_notes", "rental_terms"];

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <Panel icon={Building2} title="Business details"
        note="Printed on invoices, statements and the rental agreement, and used as {business} in messages. Leave a field blank to use the value from the server's settings (.env).">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2"><Field name="name" title="Business name" value={form.name} onChange={set} disabled={ro} placeholder={eff.name} /></div>
          <div className="sm:col-span-2"><Field name="address" title="Address" area rows={2} value={form.address} onChange={set} disabled={ro} placeholder={eff.address || "Shop address"}
            hint="A store's own address (Store Locator) is printed instead when it has one." /></div>
          <Field name="phone" title="Phone" value={form.phone} onChange={set} disabled={ro} placeholder={eff.phone} mono />
          <Field name="email" title="Email" value={form.email} onChange={set} disabled={ro} placeholder={eff.email} />
          <Field name="gstin" title="GSTIN" value={form.gstin} onChange={set} disabled={ro} placeholder={eff.gstin || "15 characters"} mono />
          <Field name="website" title="Website" value={form.website} onChange={set} disabled={ro} placeholder="www.example.in" />
        </div>
        {!ro && (
          <div className="mt-4 flex items-center gap-3">
            <PillButton primary icon={Check} disabled={busy || !BIZ.some((k) => (form[k] ?? "") !== (data.business[k] ?? ""))} onClick={() => save(BIZ, "biz")}>Save details</PillButton>
            {saved === "biz" && <span className="text-xs" style={{ ...label, color: C.green }}>Saved — new invoices and messages use it now.</span>}
          </div>
        )}
      </Panel>

      <Panel icon={FileText} title="Invoice & agreement wording" note="What's printed at the foot of every invoice, and the conditions on the rental agreement.">
        <div className="grid grid-cols-1 gap-3">
          <Field name="invoice_footer" title="Invoice footer" value={form.invoice_footer} onChange={set} disabled={ro} placeholder={data.standard.invoice_footer} />
          <Field name="signatory_label" title="Signature line (under “For business name”)" value={form.signatory_label} onChange={set} disabled={ro} placeholder={data.standard.signatory_label} />
          <Field name="invoice_notes" title="Terms & notes on every invoice (one per line)" area rows={3} value={form.invoice_notes} onChange={set} disabled={ro}
            placeholder={"e.g. Goods once sold will not be taken back.\nSubject to Delhi jurisdiction."} hint="Printed under the remarks, above the signature. Leave blank for none." />
          <Field name="rental_terms" title="Rental agreement conditions (one per line)" area rows={6} value={form.rental_terms} onChange={set} disabled={ro}
            placeholder={data.standard.rental_terms}
            hint="Blank uses the standard 10 conditions shown faintly above. {business} is replaced with the business name. Conditions typed on an agreement itself are still added after these." />
          {!ro && !form.rental_terms && (
            <button type="button" className="self-start text-xs underline" style={{ ...label, color: C.stamp }} onClick={() => set("rental_terms", data.standard.rental_terms)}>
              Start from the standard conditions
            </button>
          )}
        </div>
        {!ro && (
          <div className="mt-4 flex items-center gap-3">
            <PillButton primary icon={Check} disabled={busy || !DOCS.some((k) => (form[k] ?? "") !== (data.business[k] ?? ""))} onClick={() => save(DOCS, "docs")}>Save wording</PillButton>
            {saved === "docs" && <span className="text-xs" style={{ ...label, color: C.green }}>Saved.</span>}
          </div>
        )}
      </Panel>
      {error && <div className="xl:col-span-2"><ErrorNote message={error} /></div>}
      {dirty && !ro && <p className="text-[11px] xl:col-span-2" style={label}>You have unsaved changes.</p>}
    </div>
  );
}

function PartEditor({ title, icon: Icon, value, onChange, rows, allowed, required, samples, standard }) {
  const ref = useRef(null);
  const problems = textProblems(value, allowed, required);
  const add = (name) => {
    const el = ref.current;
    const [next, cursor] = insertAt(value, el?.selectionStart, el?.selectionEnd, `{${name}}`);
    onChange(next);
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(cursor, cursor); } });
  };
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs" style={{ ...label, fontWeight: 700, color: C.ink }}><Icon size={13} /> {title}</span>
        {value !== standard && (
          <button type="button" className="flex items-center gap-1 text-[11px] underline" style={label} onClick={() => onChange(standard)}><RotateCcw size={11} /> standard wording</button>
        )}
      </div>
      {rows === 1 ? (
        <input ref={ref} value={value} onChange={(e) => onChange(e.target.value)} className="mt-1 block w-full px-2.5 py-2 text-sm outline-none" style={input} />
      ) : (
        <textarea ref={ref} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} className="mt-1 block w-full px-2.5 py-2 text-sm outline-none" style={{ ...input, lineHeight: 1.5 }} />
      )}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {allowed.map((name) => (
          <button key={name} type="button" title={`Insert {${name}} — e.g. ${samples[name]}`} onClick={() => add(name)}
            className="rounded-full px-2 py-0.5 text-[11px]"
            style={{ fontFamily: F.mono, color: C.stamp, backgroundColor: `color-mix(in srgb, ${C.stamp} 6%, transparent)`, border: `1px solid color-mix(in srgb, ${C.stamp} 20%, transparent)` }}>
            {`{${name}}`}
          </button>
        ))}
      </div>
      {problems.map((p) => <p key={p} className="mt-1 text-[11px]" style={{ ...label, color: C.carbon, fontWeight: 600 }}>{p}</p>)}
      <div className="mt-2 rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: C.slip2, border: `1px dashed ${C.ruleStrong}`, fontFamily: F.body, color: C.ink, whiteSpace: "pre-wrap" }}>
        <span className="mb-0.5 block text-[10px] uppercase" style={{ ...label, letterSpacing: "0.1em", fontWeight: 700 }}>Customer sees</span>
        {previewText(value, samples) || <span style={label}>—</span>}
      </div>
    </div>
  );
}

function MessageEditor({ message, business, canEdit, onSaved, savedNote }) {
  // remounted (key) for each message / saved version, so the draft starts from it
  const [draft, setDraft] = useState({ subject: message.subject, body: message.body, email_body: message.email_body });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState(savedNote || "");

  const allowed = message.placeholders.map((p) => p.name);
  const samples = Object.fromEntries(message.placeholders.map((p) => [p.name, p.sample]));
  samples.business = business.name || samples.business;
  if (business.phone) samples.business_phone = business.phone;
  const set = (k) => (v) => { setDraft((d) => ({ ...d, [k]: v })); setNote(""); };
  const changed = ["subject", "body", "email_body"].some((k) => draft[k] !== message[k]);
  const blocked = !draft.body.trim() || ["subject", "body", "email_body"].some((k) => textProblems(draft[k], allowed, k === "subject" ? [] : message.required).length);

  const save = async () => {
    setBusy(true); setError("");
    try {
      onSaved(await api.post(`/branding/messages/${message.key}/`, draft), "Saved — the next message sent uses this wording.");
    } catch (e) {
      const b = e.body || {};
      setError([].concat(b.body || [], b.subject || [], b.email_body || [], b.detail || []).join(" ") || e.message);
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setBusy(true); setError("");
    try {
      onSaved(await api.del(`/branding/messages/${message.key}/`), "Back to the standard wording.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <p style={{ fontFamily: F.display, fontWeight: 700, color: C.ink, fontSize: 16 }}>{message.label}</p>
        {message.edited ? <Pill color={C.stamp}>Edited</Pill> : <Pill color={C.inkSoft}>Standard</Pill>}
      </div>
      <p className="mt-1 text-xs" style={label}>
        <b style={{ color: C.ink }}>Sent:</b> {message.when} <span className="whitespace-nowrap">· {message.channels.map((c) => CHANNEL[c] || c).join(", ")}</span>
      </p>
      {message.edited && message.updated_by && (
        <p className="mt-0.5 text-[11px]" style={label}>Last changed by {message.updated_by}{message.updated_at ? ` on ${new Date(message.updated_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}` : ""}</p>
      )}
      <fieldset disabled={!canEdit} className="mt-4 grid gap-4">
        {message.has_subject && (
          <PartEditor title="Email subject" icon={Mail} rows={1} value={draft.subject} onChange={set("subject")} allowed={allowed} required={[]} samples={samples} standard={message.standard.subject} />
        )}
        <PartEditor title={message.channels.includes("email") && !message.has_email_body && message.channels.length > 1 ? "Message (WhatsApp / SMS and email)" : message.channels.length === 1 && message.channels[0] === "email" ? "Email" : "Message"}
          icon={MessageSquare} rows={message.body.length > 160 ? 6 : 3} value={draft.body} onChange={set("body")} allowed={allowed} required={message.required} samples={samples} standard={message.standard.body} />
        {message.has_email_body && (
          <PartEditor title="Email text" icon={Mail} rows={3} value={draft.email_body} onChange={set("email_body")} allowed={allowed} required={message.required} samples={samples} standard={message.standard.email_body} />
        )}
      </fieldset>
      <details className="mt-3 text-[11px]" style={label}>
        <summary className="cursor-pointer">What each placeholder means</summary>
        <ul className="mt-1 grid gap-0.5">
          {message.placeholders.map((p) => (
            <li key={p.name}><span style={{ fontFamily: F.mono, color: C.ink }}>{`{${p.name}}`}</span> — {p.description} <span style={{ color: C.inkSoft }}>(e.g. {p.name === "business" ? samples.business : p.sample})</span></li>
          ))}
        </ul>
      </details>
      <ErrorNote message={error} />
      {canEdit ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <PillButton primary icon={Check} disabled={busy || !changed || blocked} onClick={save}>{busy ? "Saving…" : "Save message"}</PillButton>
          {message.edited && <PillButton icon={RotateCcw} disabled={busy} onClick={reset}>Reset to standard</PillButton>}
          {changed && <button type="button" className="text-xs underline" style={label} onClick={() => setDraft({ subject: message.subject, body: message.body, email_body: message.email_body })}>Undo changes</button>}
          {note && <span className="text-xs" style={{ ...label, color: C.green }}>{note}</span>}
        </div>
      ) : (
        <p className="mt-4 text-xs" style={label}>Only the Owner or an Admin can change customer messages.</p>
      )}
    </div>
  );
}

function Messages({ data, onMessage }) {
  const [query, setQuery] = useState("");
  const [saved, setSaved] = useState({ key: "", note: "", n: 0 });
  const [key, setKey] = useState(data.messages[0]?.key);
  const shown = useMemo(() => filterMessages(data.messages, query), [data.messages, query]);
  const current = data.messages.find((m) => m.key === key) || shown[0];
  const edited = data.messages.filter((m) => m.edited).length;

  return (
    <Panel icon={MessageSquare} title="Customer messages"
      note={`Every WhatsApp, SMS and email the CRM sends a customer — ${data.messages.length} in all${edited ? `, ${edited} edited` : ""}. Pick one to change its wording; words in {braces} are filled in when it's sent.`}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="min-w-0">
          <label className="flex items-center gap-2 px-2.5 py-1.5" style={input}>
            <Search size={14} style={{ color: C.inkSoft }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a message… e.g. invoice, warranty" className="w-full bg-transparent text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: "none", boxShadow: "none" }} />
          </label>
          <div className="mt-2 max-h-[560px] overflow-y-auto pr-1">
            {data.groups.map((group) => {
              const items = shown.filter((m) => m.group === group);
              if (!items.length) return null;
              return (
                <div key={group} className="mt-3 first:mt-1">
                  <Eyebrow>{group}</Eyebrow>
                  <div className="mt-1 grid gap-1">
                    {items.map((m) => {
                      const active = current?.key === m.key;
                      return (
                        <button key={m.key} type="button" onClick={() => setKey(m.key)} data-message={m.key}
                          className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-sm"
                          style={{ fontFamily: F.body, color: active ? C.onAccent : C.ink, backgroundColor: active ? C.stamp : "transparent", border: `1px solid ${active ? C.stamp : C.rule}` }}>
                          <span className="min-w-0 truncate">{m.label}</span>
                          {m.edited && <span className="shrink-0 rounded-full px-1.5 text-[10px]" style={{ fontWeight: 700, color: active ? C.stamp : C.onAccent, backgroundColor: active ? C.onAccent : C.stamp }}>edited</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {!shown.length && <p className="mt-3 text-xs" style={label}>No message matches “{query}”.</p>}
          </div>
        </div>
        <div className="min-w-0 rounded-xl p-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
          {current ? <MessageEditor key={`${current.key}-${saved.n}`} message={current} business={data.effective} canEdit={data.can_edit}
            savedNote={saved.key === current.key ? saved.note : ""}
            onSaved={(row, note) => { onMessage(row); setSaved((s) => ({ key: row.key, note, n: s.n + 1 })); }} /> : <p className="text-sm" style={label}>Pick a message.</p>}
        </div>
      </div>
    </Panel>
  );
}

export default function BusinessMessages() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/branding/").then(setData).catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner />;

  const onMessage = (row) => setData((d) => ({ ...d, messages: d.messages.map((m) => (m.key === row.key ? row : m)) }));
  return (
    <div className="grid gap-5">
      {!data.can_edit && (
        <p className="rounded-xl px-3 py-2 text-xs" style={{ ...label, border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          You can see what customers are sent. Only the Owner or an Admin can change it.
        </p>
      )}
      <BusinessForm data={data} onSaved={setData} />
      <Messages data={data} onMessage={onMessage} />
    </div>
  );
}
