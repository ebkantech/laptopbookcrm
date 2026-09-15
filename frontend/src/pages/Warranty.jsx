import { useEffect, useState } from "react";
import { Phone, Plus, Search, ShieldCheck, X } from "lucide-react";
import { C, F, fmt } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Locked, Pill, Spinner } from "../components/Atoms";

const SECTION_COLOR = { Sales: C.stamp, Repair: C.amber, Rental: C.blue, Other: C.inkSoft };
const STATUS_COLOR = { Active: C.green, "Expiring soon": C.amber, Expired: C.carbon };

function NewWarrantyModal({ parties, onClose, onCreated }) {
  const [partyId, setPartyId] = useState(parties[0]?.id || "");
  const [section, setSection] = useState("Sales");
  const [eligible, setEligible] = useState(null);
  const [invoiceId, setInvoiceId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [itemLabel, setItemLabel] = useState("");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!partyId || (section !== "Sales" && section !== "Repair")) { setEligible(null); return; }
    api.get(`/warranties/eligible-items/?party=${partyId}`).then(setEligible);
    setInvoiceId("");
    setTicketId("");
  }, [partyId, section]);

  const applyDefaultTerm = (days) => {
    const start = startDate || new Date().toISOString().slice(0, 10);
    const d = new Date(start);
    d.setDate(d.getDate() + days);
    setEndDate(d.toISOString().slice(0, 10));
  };

  const submit = async () => {
    setError("");
    if (!partyId) return setError("Pick a customer.");
    if (!itemLabel.trim()) return setError("Describe what the warranty covers.");
    if (!startDate || !endDate) return setError("Set both a start and end date.");

    const payload = {
      party: partyId, section, item_label: itemLabel.trim(),
      start_date: startDate, end_date: endDate, notes: notes.trim(),
      invoice: section === "Sales" ? invoiceId || null : null,
      repair_ticket: section === "Repair" ? ticketId || null : null,
    };
    setBusy(true);
    try {
      const w = await api.post("/warranties/", payload);
      onCreated(w);
    } catch (e) {
      const body = e.body || {};
      setError(Object.values(body).flat().join(" ") || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>New warranty</Eyebrow>
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>

        <label className="mt-4 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Customer
          <select value={partyId} onChange={(e) => setPartyId(+e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
            {parties.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.phone}</option>)}
          </select>
        </label>

        <div className="mt-3 flex" style={{ border: `1px solid ${C.rule}` }}>
          {["Sales", "Repair", "Rental", "Other"].map((s) => (
            <button key={s} onClick={() => setSection(s)} className="flex-1 py-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: section === s ? C.onAccent : C.inkSoft, backgroundColor: section === s ? SECTION_COLOR[s] : "transparent" }}>{s}</button>
          ))}
        </div>

        {section === "Sales" && (
          <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            Eligible paid invoice
            {!eligible ? <Spinner /> : (
              <select value={invoiceId} onChange={(e) => { setInvoiceId(e.target.value); const inv = eligible.invoices.find((i) => String(i.id) === e.target.value); if (inv) { setItemLabel(inv.label.split("— ")[1] || inv.label); setStartDate(inv.date); applyDefaultTerm(365); } }}
                className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
                <option value="">Select a paid invoice…</option>
                {eligible.invoices.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
              </select>
            )}
            {eligible && !eligible.invoices.length && <span className="mt-1 block text-xs" style={{ color: C.amber }}>No paid invoices without a warranty yet for this customer.</span>}
          </label>
        )}

        {section === "Repair" && (
          <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            Eligible delivered repair
            {!eligible ? <Spinner /> : (
              <select value={ticketId} onChange={(e) => { setTicketId(e.target.value); const t = eligible.repair_tickets.find((i) => String(i.id) === e.target.value); if (t) { setItemLabel(t.label.split("— ")[1] || t.label); setStartDate(t.date); applyDefaultTerm(90); } }}
                className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
                <option value="">Select a delivered repair…</option>
                {eligible.repair_tickets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            )}
            {eligible && !eligible.repair_tickets.length && <span className="mt-1 block text-xs" style={{ color: C.amber }}>No delivered repairs without a warranty yet for this customer.</span>}
          </label>
        )}

        <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>What does it cover?
          <input value={itemLabel} onChange={(e) => setItemLabel(e.target.value)} placeholder="e.g. Dell Latitude 5420, or Rental equipment protection" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Start date
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>End date
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
          </label>
        </div>
        <div className="mt-2 flex gap-2">
          {[["90 days", 90], ["6 months", 182], ["1 year", 365]].map(([label, days]) => (
            <button key={label} onClick={() => applyDefaultTerm(days)} className="px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>{label}</button>
          ))}
        </div>

        <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Notes (optional)
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="mt-1 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <ShieldCheck size={13} /> {busy ? "Saving…" : "Register warranty"}
        </button>
      </div>
    </div>
  );
}

export default function Warranty() {
  const { can } = useSession();
  const [warranties, setWarranties] = useState(null);
  const [parties, setParties] = useState([]);
  const [error, setError] = useState("");
  const [phone, setPhone] = useState("");
  const [sectionFilter, setSectionFilter] = useState("all");
  const [adding, setAdding] = useState(false);
  const [flash, setFlash] = useState("");

  const load = (phoneQuery) => {
    const params = phoneQuery ? `?phone=${encodeURIComponent(phoneQuery)}` : "";
    api.get(`/warranties/${params}`).then((d) => setWarranties(d.results ?? d)).catch((e) => setError(e.message));
  };

  useEffect(() => {
    load("");
    api.get("/parties/").then((d) => setParties(d.results ?? d));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(phone), 300);
    return () => clearTimeout(t);
  }, [phone]);

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!warranties) return <Spinner label="Loading warranties…" />;

  const rows = sectionFilter === "all" ? warranties : warranties.filter((w) => w.section === sectionFilter);

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 20, color: C.ink }}>Warranty records</p>
          <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Look up by mobile number — shows exactly which section covers the customer, and for what</p>
        </div>
        {can("warranty.manage") && (
          <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 px-3 py-2 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
            <Plus size={14} /> New warranty
          </button>
        )}
      </div>

      {flash && (
        <div className="mt-3 flex items-center gap-2 px-3 py-2" style={{ backgroundColor: `${C.green}14`, border: `1px solid ${C.green}` }}>
          <ShieldCheck size={13} style={{ color: C.green }} />
          <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{flash}</span>
        </div>
      )}

      <div className="mt-5 flex min-w-0 items-center gap-2" style={{ borderBottom: `1px solid ${C.rule}`, maxWidth: 360 }}>
        <Phone size={15} style={{ color: C.inkSoft }} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Search by mobile number"
          className="w-full bg-transparent py-1.5 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink }} />
      </div>

      <div className="mt-4 flex gap-4 overflow-x-auto" style={{ borderBottom: `1px solid ${C.rule}` }}>
        {["all", "Sales", "Repair", "Rental", "Other"].map((s) => (
          <button key={s} onClick={() => setSectionFilter(s)} className="shrink-0 pb-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: sectionFilter === s ? C.ink : C.inkSoft, borderBottom: `2px solid ${sectionFilter === s ? C.orange : "transparent"}` }}>
            {s === "all" ? "All sections" : s}
          </button>
        ))}
      </div>

      <div className="mt-3 space-y-2">
        {rows.map((w) => (
          <div key={w.id} data-panel className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
            <div className="min-w-[180px] flex-1">
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{w.party_name}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{w.party_phone}</p>
            </div>
            <div className="min-w-[200px] flex-1">
              <p className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{w.item_label}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
                {fmt(w.start_date)} → {fmt(w.end_date)}
                {w.invoice_code && ` · ${w.invoice_code}`}{w.repair_code && ` · ${w.repair_code}`}
              </p>
            </div>
            <Pill color={SECTION_COLOR[w.section]}>{w.section}</Pill>
            <Pill color={STATUS_COLOR[w.status]}>{w.status}</Pill>
          </div>
        ))}
        {!rows.length && <p className="px-2 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No warranty records match this view.</p>}
      </div>

      {adding && (
        <NewWarrantyModal parties={parties} onClose={() => setAdding(false)}
          onCreated={(w) => { setWarranties((l) => [w, ...l]); setAdding(false); setFlash(`Warranty registered and emailed to ${w.party_name} at ${w.party_email || "their email on file"}.`); setTimeout(() => setFlash(""), 6000); }} />
      )}
    </div>
  );
}
