import { useEffect, useState } from "react";
import { Copy, KeyRound, Mail, Phone, Repeat2, Search, ShieldCheck, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { Pill, Spinner, ErrorNote } from "../components/Atoms";
import { PartyThread } from "../components/PartyThread";

const STATUS_COLOR = { Paid: C.green, "Payment link sent": C.amber, Overdue: C.carbon };


function PartyDetail({ partyId, onClose }) {
  const [party, setParty] = useState(null);
  const [portal, setPortal] = useState(null);
  const [portalLink, setPortalLink] = useState("");
  const [portalError, setPortalError] = useState("");
  const [portalBusy, setPortalBusy] = useState(false);

  useEffect(() => {
    api.get(`/parties/${partyId}/`).then(setParty);
    api.get(`/parties/${partyId}/portal-account/`).then(setPortal).catch((error) => setPortalError(error.message));
  }, [partyId]);

  async function generatePortalLink(kind) {
    setPortalBusy(true); setPortalError(""); setPortalLink("");
    try {
      const path = kind === "invite" ? "portal-invite" : "portal-reset-link";
      const data = await api.post(`/parties/${partyId}/${path}/`, {});
      setPortalLink(data.setup_url || data.reset_url);
      setPortal(await api.get(`/parties/${partyId}/portal-account/`));
    } catch (error) {
      setPortalError(error.message);
    } finally {
      setPortalBusy(false);
    }
  }
  if (!party) return null;

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 18, color: C.ink }}>{party.name}</p>
            <p className="mt-1 text-xs capitalize" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.type} · {party.customer_classification} · {party.city} · customer since {fmt(party.joined)}</p>
          </div>
          <button onClick={onClose}><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <a href={`tel:${party.phone}`} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Phone size={12} />{party.phone}</a>
          {party.email && <a href={`mailto:${party.email}`} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Mail size={12} />{party.email}</a>}
          {party.gstin && <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.gstin}</span>}
        </div>

        <section className="mt-6 rounded-lg p-4" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={15} style={{ color: C.stamp }} />Customer portal access</p>
              <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>
                {portal?.enabled ? `${portal.status} - registered phone ${portal.phone}` : "No portal account created yet."}
              </p>
            </div>
            <button disabled={portalBusy || !portal} onClick={() => generatePortalLink(portal?.status === "active" ? "reset" : "invite")} className="flex items-center gap-1.5 rounded-md px-3 py-2 text-xs text-white disabled:opacity-50" style={{ background: C.stamp }}>
              <KeyRound size={13} />{portalBusy ? "Generating..." : portal?.status === "active" ? "Generate reset link" : "Generate setup link"}
            </button>
          </div>
          {portalError && <p className="mt-3 text-xs" style={{ color: C.carbon }}>{portalError}</p>}
          {portalLink && <div className="mt-3">
            <p className="text-xs" style={{ color: C.inkSoft }}>Send this one-time 24-hour link to the customer:</p>
            <div className="mt-1 flex gap-2">
              <input readOnly value={portalLink} className="min-w-0 flex-1 rounded-md px-2 py-2 text-xs" style={{ border: `1px solid ${C.rule}`, background: C.slip }} />
              <button onClick={() => navigator.clipboard.writeText(portalLink)} className="rounded-md p-2" title="Copy link" style={{ border: `1px solid ${C.rule}` }}><Copy size={14} /></button>
            </div>
          </div>}
        </section>

        <p className="mt-6 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>WhatsApp & email</p>
        <div className="mt-3">
          <PartyThread partyId={party.id} messages={party.messages} onSent={(m) => setParty((p) => ({ ...p, messages: [...p.messages, m] }))} />
        </div>

        <p className="mt-6 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
          Transaction history — {party.invoice_count} invoice{party.invoice_count !== 1 ? "s" : ""}, {money(party.total_spent)} total
        </p>
        <div className="mt-3 space-y-2">
          {party.invoices.map((inv) => (
            <div key={inv.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{inv.code}</span>
                  {inv.recurring_interval && <Pill color={C.blue}><Repeat2 size={10} />{inv.recurring_interval}</Pill>}
                </div>
                <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  {fmt(inv.date)} · {inv.stock_point_name} · {inv.item_count} item{inv.item_count !== 1 ? "s" : ""} · {inv.pay_method}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(inv.total)}</span>
                <Pill color={STATUS_COLOR[inv.status]}>{inv.status}</Pill>
              </div>
            </div>
          ))}
          {!party.invoices.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No purchases recorded yet.</p>}
        </div>
      </div>
    </div>
  );
}

export default function Parties() {
  const [parties, setParties] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);

  const load = (q) => api.get(`/parties/${q ? `?q=${encodeURIComponent(q)}` : ""}`).then((d) => setParties(d.results ?? d)).catch((e) => setError(e.message));
  useEffect(() => { load(""); }, []);
  useEffect(() => { const t = setTimeout(() => load(query), 300); return () => clearTimeout(t); }, [query]);

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!parties) return <Spinner label="Loading parties…" />;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <header className="flex items-center gap-3 px-5 py-4 sm:px-8" style={{ borderBottom: `1px solid ${C.rule}` }}>
        <div className="flex min-w-0 flex-1 items-center gap-2" style={{ borderBottom: `1px solid ${C.rule}` }}>
          <Search size={15} style={{ color: C.inkSoft }} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a customer, dealer, or rental account"
            className="w-full bg-transparent py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink }} />
        </div>
      </header>
      <div className="flex-1 overflow-y-auto">
        {parties.map((p) => (
          <button key={p.id} onClick={() => setSelected(p.id)} data-row className="flex w-full items-center justify-between px-5 py-3.5 text-left sm:px-8" style={{ borderBottom: `1px solid ${C.rule}` }}>
            <div>
              <p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{p.name}</p>
              <p className="text-xs capitalize" style={{ fontFamily: F.mono, color: C.inkSoft }}>{p.type} · {p.customer_classification} · {p.phone}</p>
            </div>
            <div className="text-right">
              <p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(p.total_spent)}</p>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{p.invoice_count} invoice{p.invoice_count !== 1 ? "s" : ""}</p>
            </div>
          </button>
        ))}
      </div>
      {selected && <PartyDetail partyId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
