import { useEffect, useState } from "react";
import { Check, Plus, Search, X } from "lucide-react";
import { C, F } from "../../lib/theme";
import { api } from "../../lib/api";
import { useSession } from "../../context/SessionContext";
import { ErrorNote, Spinner } from "../Atoms";

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
  }, []);

  if (loadError) return <ErrorNote message={loadError} />;
  if (!parties) return <Spinner label="Loading customers…" />;

  const selected = parties.find((p) => p.id === value);

  const onCreated = (party) => {
    setParties((list) => [...list, party].sort((a, b) => a.name.localeCompare(b.name)));
    onChange(party.id);
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
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  // Same mobile number already on file -> almost certainly the same
  // customer; offer them instead of creating a duplicate.
  const phone10 = digits(form.phone).slice(-10);
  const existing = phone10.length === 10 ? parties.find((p) => digits(p.phone).slice(-10) === phone10) : null;

  const save = async () => {
    setError("");
    if (!form.name.trim()) return setError("Enter the customer's name.");
    if (digits(form.phone).length < 10) return setError("Enter a 10-digit mobile number.");
    if (existing && !window.confirm(`${existing.name} already has this number. Create a separate customer anyway?`)) return;
    setBusy(true);
    try {
      const party = await api.post("/parties/", {
        ...Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim()])),
        joined: new Date().toISOString().slice(0, 10),
      });
      onCreated(party);
    } catch (e) {
      const body = e.body || {};
      const fieldErrors = Object.entries(body).filter(([k]) => k !== "detail").map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`);
      setError(fieldErrors.join(" · ") || body.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const input = (label, key, props = {}) => (
    <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{label}
      <input value={form[key]} onChange={set(key)} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field} {...props} />
    </label>
  );

  return (
    <div className="p-3" style={{ border: `1px solid ${C.stamp}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>New customer</span>
        <button onClick={onCancel}><X size={14} style={{ color: C.inkSoft }} /></button>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {input("Name *", "name", { autoFocus: true })}
        {input("Mobile *", "phone", { placeholder: "98xxxxxxxx", inputMode: "tel" })}
        <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Type
          <select value={form.type} onChange={set("type")} className="mt-1 w-full px-2 py-1.5 text-sm outline-none" style={field}>
            <option>Retail</option><option>Dealer</option><option>Rental</option>
          </select>
        </label>
        {input("City", "city")}
        {input("Email", "email", { type: "email" })}
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
