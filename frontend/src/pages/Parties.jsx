import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Mail, Phone, RefreshCw, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { Pill, PillButton, SearchInput, Spinner, ErrorNote } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import { PartyActionsMenu, PartyEditModal } from "../components/parties/PartyActions";
import PartyInvoices from "../components/parties/PartyInvoices";
import { announcePartyChanged, PARTY_CHANGED_EVENT } from "../lib/partyEvents";
import { useSession } from "../context/SessionContext";


const WHATSAPP_CHECK_ERROR = "Unable to verify WhatsApp number. Please try again";
// recheck-whatsapp's whatsapp_status values ("unknown" is shown as pending)
const WHATSAPP_STATUS = {
  verified: { label: "WhatsApp Verified", color: C.green, icon: CheckCircle2 },
  not_verified: { label: "WhatsApp Not Verified", color: C.carbon, icon: AlertTriangle },
  pending: { label: "Verification Pending", color: C.amber, icon: Clock },
  unable: { label: "Unable to Verify", color: C.inkSoft, icon: AlertTriangle },
};

function PartyDetail({ partyId, onClose }) {
  const [party, setParty] = useState(null);
  const [partyError, setPartyError] = useState("");
  const [partyLoading, setPartyLoading] = useState(true);
  const [rechecking, setRechecking] = useState(false);
  // Outcome of the last Check WhatsApp in this popup: { phone, status: "verified" | "not_verified" | "pending" | "unable", message }.
  // Tied to the number checked, so it never shows against a different number after an edit.
  const [whatsappCheck, setWhatsappCheck] = useState(null);

  useEffect(() => {
    let alive = true;
    const loadParty = () => api.get(`/parties/${partyId}/`).then((data) => { if (alive) { setParty(data); setPartyError(""); setPartyLoading(false); } }).catch((error) => { if (alive) { setPartyError(error.message); setPartyLoading(false); } });
    loadParty();
    const onChanged = (event) => { if (event.detail?.id === partyId) loadParty(); };
    window.addEventListener(PARTY_CHANGED_EVENT, onChanged);
    return () => { alive = false; window.removeEventListener(PARTY_CHANGED_EVENT, onChanged); };
  }, [partyId]);

  async function recheckWhatsapp() {
    if (rechecking) return;
    const phone = party.phone;
    setRechecking(true);
    setWhatsappCheck(null);
    try {
      const result = await api.post(`/parties/${partyId}/recheck-whatsapp/`, {});
      setParty((p) => ({ ...p, whatsapp_verified: result.whatsapp_verified, whatsapp_checked_at: result.whatsapp_checked_at }));
      // whatsapp_status comes from the CRM's own delivery records first; "unknown" means nothing proves it
      // either way (the Meta Cloud API has no number lookup) -- shown as pending, never as "not verified".
      const status = result.whatsapp_status === "unknown" ? "pending" : result.whatsapp_status || "pending";
      const reason = result.reason || "";
      setWhatsappCheck({ phone, status, message: result.whatsapp_status === "unknown"
        ? `No delivered CRM WhatsApp message to this number yet${reason ? ` (${reason})` : ""}`
        : status === "unable" && !reason ? WHATSAPP_CHECK_ERROR : reason });
    } catch (error) {
      setWhatsappCheck({ phone, status: "unable", message: error.status === 403 ? "Your role needs Parties management permission to check WhatsApp." : WHATSAPP_CHECK_ERROR });
    } finally {
      setRechecking(false);
    }
  }

  if (!party) return <div className="fixed inset-0 z-20 flex items-end justify-center bg-slate-950/55 p-0 sm:items-center sm:p-4" onClick={onClose}><div className="w-full max-w-md rounded-t-2xl p-5 sm:rounded-2xl" data-panel style={{ background: C.slip }} onClick={(event) => event.stopPropagation()}>{partyLoading ? <Spinner label="Loading customer details…" /> : <ErrorNote message={partyError || "Couldn't load this customer."} />}<button type="button" onClick={onClose} className="mt-2 w-full rounded-lg px-3 py-2 text-sm" style={{ color: C.inkSoft, border: `1px solid ${C.rule}` }}>Close</button></div></div>;

  const checkShown = whatsappCheck?.phone === party.phone ? whatsappCheck : null;
  // a check made in this popup wins; otherwise the stored result (true / false), or nothing until checked
  const whatsappStatus = rechecking ? null
    : checkShown?.status || (party.whatsapp_verified === true ? "verified" : party.whatsapp_verified === false ? "not_verified" : null);

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88dvh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-t-2xl px-4 pb-4 sm:rounded-2xl sm:px-6 sm:pb-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        {/* Party details: the first thing in the panel (which has no top padding), pinned at its top edge while
            the rest scrolls beneath. The negative side margins stretch its background across the side padding. */}
        <div className="sticky top-0 z-10 -mx-4 px-4 pb-4 pt-3 sm:-mx-6 sm:px-6 sm:pt-4" style={{ backgroundColor: C.slip, borderBottom: `1px solid ${C.rule}`, boxShadow: "0 6px 12px -10px rgba(23,32,51,0.35)" }}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="break-words" style={{ fontFamily: F.display, fontWeight: 600, fontSize: 18, color: C.ink }}>{party.name}</p>
            <p className="mt-1 text-xs capitalize" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.type} · {party.customer_classification} · {party.city} · customer since {fmt(party.joined)}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <a href={`tel:${party.phone}`} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Phone size={12} />{party.phone}</a>
          {party.email && <a href={`mailto:${party.email}`} className="flex min-w-0 items-center gap-1.5 break-all px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Mail size={12} className="shrink-0" />{party.email}</a>}
          {party.gstin && <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.gstin}</span>}
          {whatsappStatus && (() => {
            const { label, color, icon: Icon } = WHATSAPP_STATUS[whatsappStatus];
            return <Pill color={color}><Icon size={11} />{label}</Pill>;
          })()}
          {whatsappStatus !== "verified" && (
            <PillButton icon={RefreshCw} disabled={rechecking} onClick={recheckWhatsapp}>
              {rechecking ? "Checking WhatsApp…" : whatsappStatus ? "Re-check" : "Check WhatsApp"}
            </PillButton>
          )}
        </div>
        {checkShown?.message && !rechecking && (
          <p role={checkShown.status === "unable" ? "alert" : "status"} className="mt-2 break-words text-xs" style={{ color: checkShown.status === "unable" ? C.carbon : C.inkSoft }}>{checkShown.message}.</p>
        )}
        </div>


        <PartyInvoices partyId={party.id} invoices={party.invoices} invoiceCount={party.invoice_count} totalSpent={party.total_spent} />
      </div>
    </div>
  );
}

export default function Parties() {
  const { can } = useSession();
  const [parties, setParties] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const detailIdFromPath = () => window.location.pathname.match(/^\/parties\/(\d+)\/?$/)?.[1] || null;
  const [selected, setSelectedState] = useState(detailIdFromPath);
  const [editing, setEditing] = useState(null);

  const setSelected = (id, { replace = false } = {}) => {
    const path = id ? `/parties/${id}` : "/parties";
    window.history[replace ? "replaceState" : "pushState"]({ view: "parties", partyId: id || null }, "", `${path}${window.location.search}${window.location.hash}`);
    setSelectedState(id ? String(id) : null);
  };

  useEffect(() => {
    const onPopState = () => setSelectedState(detailIdFromPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const load = (q) => api.getAll(`/parties/${q ? `?q=${encodeURIComponent(q)}` : ""}`).then(setParties).catch((e) => setError(e.message));
  useEffect(() => { load(""); }, []);
  useEffect(() => { const t = setTimeout(() => load(query), 300); return () => clearTimeout(t); }, [query]);

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!parties) return <Spinner label="Loading parties…" />;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="px-5 pt-6 sm:px-8">
        <PageHeader title="Parties" subtitle="Customers, dealers, and rental accounts" />
      </div>
      <header className="flex items-center gap-3 px-5 py-4 sm:px-8">
        <SearchInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a customer, dealer, or rental account" />
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-4 sm:px-8">
        <div className="flex flex-col gap-2.5">
          {parties.map((p) => (
            <div
              key={p.id}
              onClick={() => setSelected(p.id)}
              data-listcard
              className="group flex min-w-0 w-full items-center justify-between gap-3 px-3 py-3.5 text-left sm:px-5"
              data-selected={selected === String(p.id)}
            >
              <button type="button" className="min-w-0 flex-1 text-left">
              <p className="flex min-w-0 items-center gap-1.5 truncate text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>
                  {p.name}
                  {p.whatsapp_verified === false && <AlertTriangle size={12} style={{ color: C.carbon }} />}
              </p>
              <p className="truncate text-xs capitalize" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.type} · {p.customer_classification} · {p.phone}</p>
              </button>
              <div className="flex shrink-0 items-center gap-2">
              <div className="hidden text-right sm:block">
                <p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(p.total_spent)}</p>
                <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{p.invoice_count} invoice{p.invoice_count !== 1 ? "s" : ""}</p>
              </div>
              {can("parties.edit") && <PartyActionsMenu onEdit={() => setEditing(p)} />}
              </div>
            </div>
          ))}
          {!parties.length && <p className="px-3 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No parties match that search.</p>}
        </div>
      </div>
      {selected && <PartyDetail key={selected} partyId={selected} onClose={() => setSelected(null)} />}
      {editing && <PartyEditModal party={editing} onClose={() => setEditing(null)} onSaved={(party) => {
        setParties((items) => items.map((item) => item.id === party.id ? party : item));
        setEditing(null);
        announcePartyChanged(party);
      }} />}
    </div>
  );
}
