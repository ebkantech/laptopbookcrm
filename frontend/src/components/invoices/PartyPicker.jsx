import { useEffect, useState } from "react";
import { Check, Plus, Search, X } from "lucide-react";
import { C, F, todayISO } from "../../lib/theme";
import { api } from "../../lib/api";
import { useSession } from "../../context/SessionContext";
import { ErrorNote, Spinner } from "../Atoms";
import { announcePartyChanged, PARTY_CHANGED_EVENT } from "../../lib/partyEvents";

const field = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };
const digits = (s) => (s || "").replace(/\D/g, "");

/*
 * Customer picker for a new invoice: always loads the current customer
 * list when it opens (so customers added since the page loaded are
 * there), searches by name or phone, and can add a new customer on the
 * spot without leaving the invoice.
 */
export default function PartyPicker({ value, onChange }) {
  const { can } = useSession();
  const [parties, setParties] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api.getAll("/parties/").then(setParties).catch((e) => setLoadError(e.message));
    const syncParty = (event) => {
      const { party, id, deleted } = event.detail || {};
      setParties((list) => {
        if (!list) return list;
        if (deleted) return list.filter((item) => item.id !== id);
        if (!party) return list;
        return [...list.filter((item) => item.id !== party.id), party].sort((a, b) => a.name.localeCompare(b.name));
      });
      if (deleted && id === value) onChange(null);
    };
    window.addEventListener(PARTY_CHANGED_EVENT, syncParty);
    return () => window.removeEventListener(PARTY_CHANGED_EVENT, syncParty);
  }, [value, onChange]);

  if (loadError) return <ErrorNote message={loadError} />;
  if (!parties) return <Spinner label="Loading customers…" />;

  const selected = parties.find((p) => p.id === value);

  const onCreated = (party) => {
    setParties((list) => [...list, party].sort((a, b) => a.name.localeCompare(b.name)));
    onChange(party.id);
    announcePartyChanged(party);
    setAdding(false);
    setQuery("");
  };

  if (adding) {
    return (
      <NewCustomerForm
        initialName={query} parties={parties} onCancel={() => setAdding(false)} onCreated={onCreated}
        onUseExisting={(id) => { onChange(id); setAdding(false); setQuery(""); }}
      />
    );
  }

  if (selected) {
    return (
      <div className="flex items-center justify-between px-3 py-2" style={{ ...field, backgroundColor: C.slip2 }}>
        <div className="min-w-0">
          <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{selected.name}</p>
          <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{[selected.phone, selected.city, selected.type].filter(Boolean).join(" · ")}</p>
        </div>
        <button onClick={() => onChange(null)} className="text-xs underline" style={{ fontFamily: F.body, color: C.inkSoft }}>Change</button>
      </div>
    );
  }

  const q = query.trim().toLowerCase();
  // A query with no letters is a phone number; anything else is a name.
  const qDigits = /[a-z]/i.test(query) ? "" : digits(query);
  const matches = (q
    ? parties.filter((p) => p.name.toLowerCase().includes(q) || (qDigits.length >= 3 && digits(p.phone).includes(qDigits)))
    : parties
  ).slice(0, 8);

  return (
    <div>
      <div className="flex items-center gap-2 px-2" style={field}>
        <Search size={13} style={{ color: C.inkSoft }} />
        <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Search ${parties.length} customers by name or phone`} className="w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink }} />
      </div>
      <div className="mt-1 max-h-48 overflow-y-auto" style={{ border: `1px solid ${C.rule}` }}>
        {matches.map((p) => (
          <button key={p.id} onClick={() => onChange(p.id)} className="flex w-full items-center justify-between px-3 py-1.5 text-left" style={{ borderBottom: `1px solid ${C.rule}` }}>
            <span className="truncate text-sm" style={{ fontFamily: F.body, color: C.ink }}>{p.name}</span>
            <span className="ml-2 shrink-0 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.phone}</span>
          </button>
        ))}
        {!matches.length && <p className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No customer matches "{query}".</p>}
      </div>
      {can("parties.manage") && (
        <button onClick={() => setAdding(true)} className="mt-2 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>
          <Plus size={12} /> Add new customer{q ? ` "${query.trim()}"` : ""}
        </button>
      )}
    </div>
  );
}

function NewCustomerForm({ initialName, parties, onCancel, onCreated, onUseExisting }) {
  // Prefill from what was searched: no letters means it was a phone number.
  const searchedPhone = !/[a-z]/i.test(initialName) && /\d/.test(initialName);
  const [form, setForm] = useState({
    name: searchedPhone ? "" : initialName.trim(), phone: searchedPhone ? initialName.trim() : "",
    type: "Retail", email: "", city: "", gstin: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  // Same mobile number already on file -> almost certainly the same
  // customer; offer them instead of creating a duplicate.
  const phone10 = digits(form.phone).slice(-10);
  const existing = phone10.length === 10 ? parties.find((p) => digits(p.phone).slice(-10) === phone10) : null;

  const save = async () => {
    setError("");
    const cleaned = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim()]));
    const nextErrors = {};
    if (!cleaned.name) nextErrors.name = "Enter the customer's name.";
    const phoneDigits = digits(cleaned.phone);
    if (phoneDigits.length < 10 || phoneDigits.length > 15) nextErrors.phone = "Enter a valid phone number with 10 to 15 digits.";
    if (!cleaned.type) nextErrors.type = "Choose a customer type.";
    if (!cleaned.city) nextErrors.city = "Enter the customer's city.";
    if (!cleaned.email) nextErrors.email = "Enter the customer's email address.";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleaned.email)) nextErrors.email = "Enter a valid email address.";
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    if (existing && !window.confirm(`${existing.name} already has this number. Create a separate customer anyway?`)) return;
    setBusy(true);
    try {
      const party = await api.post("/parties/", {
        ...cleaned,
        joined: todayISO(),
      });
      onCreated(party);
    } catch (e) {
      const body = e.body || {};
      const apiFieldErrors = Object.fromEntries(Object.entries(body).filter(([k]) => k !== "detail").map(([k, v]) => [k, [].concat(v).join(" ") ]));
      setFieldErrors(apiFieldErrors);
      setError(body.detail || (!Object.keys(apiFieldErrors).length ? e.message : "Please correct the highlighted fields."));
    } finally {
      setBusy(false);
    }
  };

  const input = (label, key, props = {}) => (
    <label className="block min-w-0 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{label}
      <input required={key !== "gstin"} aria-invalid={!!fieldErrors[key]} value={form[key]} onChange={(e) => { set(key)(e); setFieldErrors((old) => ({ ...old, [key]: "" })); }} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, borderColor: fieldErrors[key] ? C.carbon : C.rule }} {...props} />
      {fieldErrors[key] && <span className="mt-1 block text-[11px]" style={{ color: C.carbon }}>{fieldErrors[key]}</span>}
    </label>
  );

  return (
    <div className="p-3" style={{ border: `1px solid ${C.stamp}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>New customer</span>
        <button type="button" onClick={onCancel} aria-label="Cancel" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={14} style={{ color: C.inkSoft }} /></button>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {input("Name *", "name", { autoFocus: true })}
        {input("Mobile *", "phone", { placeholder: "98xxxxxxxx", inputMode: "tel" })}
        <label className="block min-w-0 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Type *
          <select required aria-invalid={!!fieldErrors.type} value={form.type} onChange={(e) => { set("type")(e); setFieldErrors((old) => ({ ...old, type: "" })); }} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={{ ...field, borderColor: fieldErrors.type ? C.carbon : C.rule }}>
            <option>Retail</option><option>Dealer</option><option>Rental</option>
          </select>
          {fieldErrors.type && <span className="mt-1 block text-[11px]" style={{ color: C.carbon }}>{fieldErrors.type}</span>}
        </label>
        {input("City *", "city")}
        {input("Email *", "email", { type: "email" })}
        {input("GSTIN", "gstin", { placeholder: "Business customers only" })}
      </div>
      {existing && (
        <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.amber }}>
          This number belongs to <b>{existing.name}</b>.{" "}
          <button onClick={() => onUseExisting(existing.id)} className="underline" style={{ color: C.stamp, fontWeight: 600 }}>Use {existing.name} instead</button>
        </p>
      )}
      <ErrorNote message={error} />
      <button onClick={save} disabled={busy} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
        <Check size={12} /> {busy ? "Saving…" : "Save customer and use on this invoice"}
      </button>
    </div>
  );
}
