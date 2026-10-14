import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCircle2, Copy, KeyRound, Mail, Phone, RefreshCw, Repeat2, ShieldCheck, X, Ban } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { Pill, PillButton, SearchInput, Spinner, ErrorNote } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import { PartyThread } from "../components/PartyThread";
import { PartyActionsMenu, PartyEditModal } from "../components/parties/PartyActions";
import { announcePartyChanged, PARTY_CHANGED_EVENT } from "../lib/partyEvents";
import { copyText } from "../lib/copyText";
import { useSession } from "../context/SessionContext";

const STATUS_COLOR = { Paid: C.green, "Payment link sent": C.amber, Overdue: C.carbon };

// Backend timestamps carry their offset; show them in the viewer's local time with the zone named.
const fmtDateTime = (value) => new Date(value).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });

const OTP_RE = /^\d{6}$/;

function PartyDetail({ partyId, onClose }) {
  const { can } = useSession();
  // { [messageId]: { otp, status, label, sequence } } -- portal.manage staff only
  const [otpHistory, setOtpHistory] = useState({});
  const [otpRefresh, setOtpRefresh] = useState(0);
  const otpStamp = useRef("");
  const knownOtpEntries = useRef(new Set());
  const [party, setParty] = useState(null);
  const [partyError, setPartyError] = useState("");
  const [partyLoading, setPartyLoading] = useState(true);
  const [portal, setPortal] = useState(null);
  const [portalLink, setPortalLink] = useState("");
  const [portalError, setPortalError] = useState("");
  const [deliveryNote, setDeliveryNote] = useState("");
  const [linkPolicy, setLinkPolicy] = useState(null);
  const [copyStatus, setCopyStatus] = useState("");
  const copyTimer = useRef(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [portalBusy, setPortalBusy] = useState(false);
  const [rechecking, setRechecking] = useState(false);

  useEffect(() => {
    let alive = true;
    const loadParty = () => api.get(`/parties/${partyId}/`).then((data) => { if (alive) { setParty(data); setPartyError(""); setPartyLoading(false); } }).catch((error) => { if (alive) { setPartyError(error.message); setPartyLoading(false); } });
    loadParty();
    api.get(`/parties/${partyId}/portal-account/`).then(setPortal).catch((error) => setPortalError(error.message));
    const onChanged = (event) => { if (event.detail?.id === partyId) loadParty(); };
    window.addEventListener(PARTY_CHANGED_EVENT, onChanged);
    return () => { alive = false; window.removeEventListener(PARTY_CHANGED_EVENT, onChanged); };
  }, [partyId]);

  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  // Every code issued to this customer, each shown inside its OWN email-history
  // entry (stored entries keep the code masked; the digits come from the
  // encrypted, portal.manage-only /portal-otps/ endpoint). Re-checked every 15 s
  // and on focus: a customer's resend adds a new entry, so when the set of
  // codes (or a status) changes the party is reloaded to show it.
  const canSeeOtp = can("portal.manage");
  const portalEnabled = Boolean(portal?.enabled);
  useEffect(() => {
    if (!canSeeOtp || !portalEnabled) { setOtpHistory({}); otpStamp.current = ""; knownOtpEntries.current = new Set(); return undefined; }
    let alive = true;
    const check = async () => {
      let rows = [];
      try { rows = (await api.get(`/parties/${partyId}/portal-otps/`)).otps || []; }
      catch { rows = []; } // 503: display not configured -- entries stay masked
      if (!alive) return;
      const byMessage = {};
      rows.forEach((row) => {
        if (row.message_id) byMessage[row.message_id] = { otp: OTP_RE.test(row.otp || "") ? row.otp : "", status: row.status, label: row.label, sequence: row.sequence };
      });
      const stamp = rows.map((row) => `${row.message_id}:${row.status}`).join("|");
      const newEntry = rows.some((row) => row.message_id && !knownOtpEntries.current.has(row.message_id));
      rows.forEach((row) => row.message_id && knownOtpEntries.current.add(row.message_id));
      if (stamp !== otpStamp.current) {
        otpStamp.current = stamp;
        if (newEntry) api.get(`/parties/${partyId}/`).then((data) => { if (alive) setParty(data); }).catch(() => {});
      }
      setOtpHistory(byMessage);
    };
    check();
    const id = window.setInterval(() => { if (document.visibilityState === "visible") check(); }, 15000);
    window.addEventListener("focus", check);
    return () => { alive = false; window.clearInterval(id); window.removeEventListener("focus", check); };
  }, [partyId, canSeeOtp, portalEnabled, otpRefresh]);

  async function recheckWhatsapp() {
    setRechecking(true);
    setPortalError("");
    try {
      const result = await api.post(`/parties/${partyId}/recheck-whatsapp/`, {});
      setParty((p) => ({ ...p, whatsapp_verified: result.whatsapp_verified, whatsapp_checked_at: result.whatsapp_checked_at }));
    } catch (error) {
      setPortalError(error.message);
    } finally {
      setRechecking(false);
    }
  }

  async function generatePortalLink(kind) {
    setPortalBusy(true); setPortalError(""); setPortalLink(""); setDeliveryNote(""); setCopyStatus(""); setLinkPolicy(null);
    try {
      const path = kind === "invite" ? "portal-invite" : "portal-reset-link";
      const data = await api.post(`/parties/${partyId}/${path}/`, {});
      setPortalLink(data.setup_url || data.reset_url);
      setLinkPolicy({ policy: data.link_policy, expiresAt: data.invite_expires_at || data.expires_at, otpMinutes: data.otp_ttl_minutes || 30 });
      // only staff with portal.manage receive `otp`; never derived from the (masked) chat record
      if (OTP_RE.test(data.otp || "") && data.otp_message_id)
        setOtpHistory((current) => ({ ...current, [data.otp_message_id]: { otp: data.otp, status: "active", label: "Portal Invitation Generated", sequence: 1 } }));
      setOtpRefresh((n) => n + 1);
      // email_delivery: "sent" (real email) or "console" (no SMTP configured: printed to the server console only).
      // The code itself is never shown in the CRM -- the Email chat keeps a masked copy.
      setDeliveryNote((data.email_delivery === "sent"
        ? `The verification code was emailed to ${data.email_sent_to} only. The link is saved in the WhatsApp chat below; the Email chat keeps a record with the code masked.`
        : "No email provider is configured, so the verification email was only printed to the server console (development). The Email chat below keeps a record with the code masked.")
        + whatsappNote(data.whatsapp_delivery));
      const [updatedParty, updatedPortal] = await Promise.all([
        api.get(`/parties/${partyId}/`),
        api.get(`/parties/${partyId}/portal-account/`),
      ]);
      setParty(updatedParty);
      setPortal(updatedPortal);
    } catch (error) {
      setPortalError(error.message);
    } finally {
      setPortalBusy(false);
    }
  }
  async function copyPortalLink(link) {
    window.clearTimeout(copyTimer.current);
    setCopyStatus("");
    try {
      await copyText(link);
      setCopyStatus("Copied");
      // "Copied" is a brief confirmation; it hides itself after 2 seconds.
      copyTimer.current = window.setTimeout(() => setCopyStatus(""), 2000);
    } catch (error) {
      setCopyStatus(error.message || "Couldn't copy the link.");
    }
  }
  async function revokePortal() {
    if (!window.confirm(`Revoke portal links for ${party.name}? Previously generated links will stop working.`)) return;
    setRevokeBusy(true);
    setPortalError("");
    try {
      await api.post(`/parties/${partyId}/revoke-portal-access/`, {});
      setPortal(await api.get(`/parties/${partyId}/portal-account/`));
      setPortalLink(""); setDeliveryNote(""); setCopyStatus(""); setLinkPolicy(null); setOtpRefresh((n) => n + 1);
    } catch (error) {
      setPortalError(error.message);
    } finally {
      setRevokeBusy(false);
    }
  }
  if (!party) return <div className="fixed inset-0 z-20 flex items-end justify-center bg-slate-950/55 p-0 sm:items-center sm:p-4" onClick={onClose}><div className="w-full max-w-md rounded-t-2xl p-5 sm:rounded-2xl" data-panel style={{ background: C.slip }} onClick={(event) => event.stopPropagation()}>{partyLoading ? <Spinner label="Loading customer details…" /> : <ErrorNote message={partyError || "Couldn't load this customer."} />}<button type="button" onClick={onClose} className="mt-2 w-full rounded-lg px-3 py-2 text-sm" style={{ color: C.inkSoft, border: `1px solid ${C.rule}` }}>Close</button></div></div>;

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[88dvh] w-full max-w-2xl overflow-y-auto rounded-t-2xl p-4 sm:rounded-2xl sm:p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 18, color: C.ink }}>{party.name}</p>
            <p className="mt-1 text-xs capitalize" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.type} · {party.customer_classification} · {party.city} · customer since {fmt(party.joined)}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <a href={`tel:${party.phone}`} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Phone size={12} />{party.phone}</a>
          {party.email && <a href={`mailto:${party.email}`} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}><Mail size={12} />{party.email}</a>}
          {party.gstin && <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{party.gstin}</span>}
          {party.whatsapp_verified === true && <Pill color={C.green}><CheckCircle2 size={11} />WhatsApp verified</Pill>}
          {party.whatsapp_verified === false && (
            <>
              <Pill color={C.carbon}><AlertTriangle size={11} />No WhatsApp on this number</Pill>
              <PillButton icon={RefreshCw} disabled={rechecking} onClick={recheckWhatsapp}>{rechecking ? "Checking…" : "Re-check"}</PillButton>
            </>
          )}
          {party.whatsapp_verified == null && (
            <PillButton icon={RefreshCw} disabled={rechecking} onClick={recheckWhatsapp}>{rechecking ? "Checking…" : "Check WhatsApp"}</PillButton>
          )}
        </div>

        <section className="mt-6 rounded-lg p-4" style={{ backgroundColor: C.slip2, border: `1px solid ${C.rule}` }}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={15} style={{ color: C.stamp }} />Customer portal access</p>
              <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>
                {portal?.enabled ? `${portal.status} - registered phone ${portal.phone}` : "No portal account created yet."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {portal?.enabled && portal.status !== "revoked" && <PillButton icon={Ban} disabled={revokeBusy || portalBusy} onClick={revokePortal}>{revokeBusy ? "Revoking…" : "Revoke links"}</PillButton>}
              <PillButton icon={KeyRound} primary disabled={portalBusy || !portal} onClick={() => generatePortalLink(portal?.status === "active" ? "reset" : "invite")}>
                {portalBusy ? "Generating..." : portal?.status === "active" ? "Generate reset link" : "Generate setup link"}
              </PillButton>
            </div>
          </div>
          {portalError && <p className="mt-3 text-xs" style={{ color: C.carbon }}>{portalError}</p>}
          {portalLink && <div className="mt-3">
            <p className="text-xs" style={{ color: C.inkSoft }}>
              {linkPolicy?.policy === "rental_tenure"
                ? "This reusable customer portal link remains valid until the qualifying rental tenure ends"
                : "This reusable customer portal link is valid for 24 hours after creation"}
              {linkPolicy?.expiresAt && <> (until <b>{fmtDateTime(linkPolicy.expiresAt)}</b>)</>}. Send it to the customer:
            </p>
            <div className="mt-1 flex min-w-0 items-center gap-2">
              <input readOnly value={portalLink} aria-label="Generated portal link" onFocus={(event) => event.target.select()} className="min-w-0 flex-1 rounded-md px-2 py-2 text-xs" style={{ border: `1px solid ${C.rule}`, background: C.slip }} />
              <button type="button" onClick={() => copyPortalLink(portalLink)} aria-label="Copy portal link" title="Copy link" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-black/5" style={{ color: copyStatus === "Copied" ? C.green : C.inkSoft, border: `1px solid ${C.rule}` }}>
                {copyStatus === "Copied" ? <Check size={16} /> : <Copy size={16} />}
              </button>
            </div>
            {copyStatus && <p role="status" className="mt-1 break-words text-xs" style={{ color: copyStatus === "Copied" ? C.green : C.carbon }}>{copyStatus}</p>}
            <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>The verification code expires {linkPolicy?.otpMinutes || 30} minutes after it is issued. Requesting a new code invalidates the previous code.</p>
            {deliveryNote && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>{deliveryNote}</p>}
          </div>}
        </section>

        <p className="mt-6 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>WhatsApp & email</p>
        <div className="mt-3">
          <PartyThread partyId={party.id} messages={party.messages} otpByMessage={otpHistory}
            onChanged={(message) => setParty((current) => ({ ...current, messages: current.messages.some((item) => item.id === message.id) ? current.messages.map((item) => item.id === message.id ? message : item) : [...current.messages, message] }))}
            onHidden={(id) => setParty((current) => ({ ...current, messages: current.messages.filter((message) => message.id !== id) }))} />
        </div>

        <p className="mt-6 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
          Transaction history — {party.invoice_count} invoice{party.invoice_count !== 1 ? "s" : ""}, {money(party.total_spent)} total
        </p>
        <div className="mt-3 space-y-2">
          {party.invoices.map((inv) => (
            <div key={inv.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5 rounded-xl" style={{ backgroundColor: C.slip2 }}>
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

// What actually happened on WhatsApp for a portal link -- never "sent"
// unless Meta accepted the message.
function whatsappNote(delivery) {
  if (!delivery) return "";
  if (delivery.status === "sent") return " WhatsApp: the link was sent through the WhatsApp API (accepted by Meta).";
  if (delivery.status === "simulated") return " WhatsApp: not sent — the WhatsApp API is in console (simulation) mode.";
  return ` WhatsApp: not sent${delivery.reason ? ` — ${delivery.reason}` : ""}.`;
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
      {selected && <PartyDetail partyId={selected} onClose={() => setSelected(null)} />}
      {editing && <PartyEditModal party={editing} onClose={() => setEditing(null)} onSaved={(party) => {
        setParties((items) => items.map((item) => item.id === party.id ? party : item));
        setEditing(null);
        announcePartyChanged(party);
      }} />}
    </div>
  );
}
