import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertOctagon, Camera, Check, CircleCheck, CircleX, Clock3, Hourglass, Copy, History, Laptop, Link2, MessageCircle, MessageSquareDiff, MessageSquarePlus, MessageSquareText, Phone,
  Plus, Send, ShieldAlert, ShieldCheck, UserPlus, X,
} from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { PARTY_CHANGED_EVENT } from "../lib/partyEvents";
import { copyText } from "../lib/copyText";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Pill, PillButton, SearchInput, Spinner, ErrorNote } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import { PartyChatModal } from "../components/PartyThread";
import RentalAgreementModal from "../components/rentals/RentalAgreementModal";
import RentInvoices from "../components/rentals/RentInvoices";
import DeviceHandoverModal from "../components/rentals/DeviceHandoverModal";
import RentalDevicesModal from "../components/rentals/RentalDevicesModal";
import ApprovalHistoryModal from "../components/rentals/ApprovalHistoryModal";
import { APPROVAL_STATUS, RENTAL_STATUS, fmtDateTime, statusOf } from "../components/rentals/approvalStatus";

const BAND_COLOR = { "High risk": C.carbon, Watch: C.amber, Healthy: C.green };
const ISSUE_STATUS_COLOR = { Open: C.carbon, "In progress": C.amber, Resolved: C.green };

function RaiseIssueModal({ rentalId, onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const issue = await api.post("/rental-issues/", { rental: rentalId, title: title.trim(), description: description.trim() });
      onCreated(issue);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between"><Eyebrow>Raise an issue</Eyebrow><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button></div>
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Log what the client is reporting about their rented equipment.</p>
        <div className="mt-4 space-y-3">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Screen flickering" className="w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="Details the client gave you" className="w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </div>
        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.carbon, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <AlertOctagon size={13} /> {busy ? "Raising…" : "Raise issue"}
        </button>
      </div>
    </div>
  );
}

function IssueRow({ issue, staff, onAssigned, onResolved }) {
  const { can } = useSession();
  const [assigning, setAssigning] = useState(false);

  const assign = async (userId) => {
    const updated = await api.post(`/rental-issues/${issue.id}/assign/`, { assigned_to: userId });
    onAssigned(updated);
    setAssigning(false);
  };
  const resolve = async () => {
    const updated = await api.post(`/rental-issues/${issue.id}/resolve/`);
    onResolved(updated);
  };

  return (
    <div className="px-3 py-2.5 rounded-xl" style={{ backgroundColor: C.slip2 }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{issue.title}</p>
          {issue.description && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{issue.description}</p>}
          <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
            Raised {new Date(issue.raised_at).toLocaleDateString("en-IN")}
            {issue.assigned_to_name && ` · assigned to ${issue.assigned_to_name}`}
          </p>
        </div>
        <Pill color={ISSUE_STATUS_COLOR[issue.status]}>{issue.status}</Pill>
      </div>

      {can("rentals.manage") && issue.status !== "Resolved" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {assigning ? (
            <select autoFocus onBlur={() => setAssigning(false)} onChange={(e) => e.target.value && assign(+e.target.value)}
              className="bg-transparent px-2 py-1 text-xs outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              <option value="">Assign to…</option>
              {staff.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>)}
            </select>
          ) : (
            <button onClick={() => setAssigning(true)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
              <UserPlus size={11} /> {issue.assigned_to_name ? "Reassign" : "Assign"}
            </button>
          )}
          <button onClick={resolve} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
            <Check size={11} /> Mark resolved
          </button>
        </div>
      )}
    </div>
  );
}

function RentalActionModal({ rental, action, onClose, onCompleted }) {
  const labels = {
    approve: ["Admin / Super Admin approval", "Record approval"],
    cancel: ["Cancel rental agreement", "Cancel agreement"],
    close: ["Close rental agreement", "Close and release assets"],
  };
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!reason.trim()) return setError("A reason is required for the audit trail.");
    setBusy(true);
    setError("");
    try {
      const endpoint = action === "approve" ? "approve-on-behalf" : action;
      onCompleted(await api.post(`/rentals/${rental.id}/${endpoint}/`, { reason: reason.trim() }));
    } catch (requestError) {
      setError(requestError.body?.detail || Object.values(requestError.body || {}).flat().join(" ") || requestError.message);
    } finally {
      setBusy(false);
    }
  };

  return <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}><div className="w-full max-w-md p-6" data-panel style={{ backgroundColor: C.slip }} onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between"><Eyebrow>{labels[action][0]}</Eyebrow><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button></div><p className="mt-2 text-sm" style={{ color: C.inkSoft }}>{rental.agreement_code} · {rental.party_name}</p><textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} rows={3} placeholder="Required reason" className="mt-4 w-full bg-transparent p-3 text-sm" style={{ border: `1px solid ${C.rule}` }} /><ErrorNote message={error} /><button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: action === "cancel" ? C.carbon : action === "approve" ? C.green : C.blue, color: C.onAccent, opacity: busy ? 0.6 : 1 }}><ShieldCheck size={13} /> {busy ? "Saving…" : labels[action][1]}</button></div></div>;
}

/* The approval link staff just generated -- shown until dismissed so it can
 * be copied or sent. The link wraps instead of overflowing on a phone. */
/* What send_approval_link_whatsapp reported -- "sent" only when Meta
 * accepted the message and returned its id. */
function apiSendNote(delivery) {
  if (!delivery) return null;
  if (delivery.status === "sent") return { ok: true, text: `Sent through the WhatsApp API${delivery.template ? ` (template ${delivery.template})` : ""} — Meta accepted it. Delivery to the phone is confirmed separately.` };
  if (delivery.status === "simulated") return { ok: false, text: "WhatsApp API isn't switched on (console mode) — nothing was sent. Use the manual WhatsApp button." };
  if (delivery.status === "skipped") return { ok: false, text: `Not sent: ${delivery.reason || "no phone number on file"}.` };
  return { ok: false, text: `Not sent: ${delivery.reason || "the WhatsApp API rejected the message"}. You can retry, or send it manually.` };
}

function ApprovalLinkPanel({ link, onDismiss }) {
  const [copyState, setCopyState] = useState("");
  const [apiState, setApiState] = useState({ busy: false, delivery: null });
  const apiLive = link.provider === "meta_cloud";
  const apiSent = apiState.delivery?.status === "sent";
  const sendViaApi = async () => {
    if (apiState.busy || apiSent) return;
    setApiState({ busy: true, delivery: null });
    try {
      const result = await api.post(`/rentals/${link.rentalId}/approval-link/send-whatsapp/`, { approval_url: link.url });
      setApiState({ busy: false, delivery: result.whatsapp_delivery });
    } catch (requestError) {
      setApiState({ busy: false, delivery: { status: "failed", reason: requestError.body?.detail || requestError.message } });
    }
  };
  const note = apiSendNote(apiState.delivery);
  const copy = async () => {
    try {
      await copyText(link.url);
      setCopyState("copied");
      setTimeout(() => setCopyState(""), 2000);
    } catch (e) {
      setCopyState(e.message || "Copy failed. Select and copy the link manually.");
    }
  };
  const btn = "flex min-h-[40px] items-center justify-center gap-1.5 rounded-full px-4 text-xs";
  return (
    <section role="status" aria-label="Approval link" className="mt-4 rounded-xl p-3 sm:p-4" style={{ border: `1px solid ${C.green}55`, backgroundColor: `${C.green}0d` }}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>
            <Link2 size={14} style={{ color: C.green }} /> Approval link v{link.version} ready{link.agreementCode && ` · ${link.agreementCode}`}
          </p>
          <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            <Clock3 size={12} className="mr-1 inline" />Valid until {fmtDateTime(link.expiresAt)} ({link.hours || 24} h). Any earlier unused link was revoked.
          </p>
        </div>
        <button type="button" aria-label="Dismiss approval link" className="-m-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-black/5" onClick={onDismiss}><X size={15} /></button>
      </div>
      <p className="mt-2 select-all break-all rounded-lg px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.ink, backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>{link.url}</p>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
        <button type="button" onClick={copy} className={btn} style={{ border: `1px solid ${copyState === "copied" ? C.green : C.rule}`, backgroundColor: C.slip, color: copyState === "copied" ? C.green : C.ink, fontWeight: 600 }}>
          {copyState === "copied" ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy link</>}
        </button>
        {apiLive && link.rentalId && (
          <button type="button" onClick={sendViaApi} disabled={apiState.busy || apiSent} className={`${btn} disabled:opacity-70`} style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 600 }}>
            {apiSent ? <><Check size={13} /> Sent via WhatsApp API</> : <><Send size={13} /> {apiState.busy ? "Sending…" : apiState.delivery ? "Retry WhatsApp API send" : "Send via WhatsApp API"}</>}
          </button>
        )}
        {link.whatsappUrl && <a href={link.whatsappUrl} target="_blank" rel="noreferrer" className={btn} style={apiLive ? { border: `1px solid ${C.rule}`, backgroundColor: C.slip, color: C.ink, fontWeight: 600, textDecoration: "none" } : { backgroundColor: C.green, color: C.onAccent, fontWeight: 600, textDecoration: "none" }}><MessageCircle size={13} style={apiLive ? { color: C.green } : undefined} /> {apiLive ? "Send manually in WhatsApp" : "Send via WhatsApp"}</a>}
      </div>
      {note && <p role="status" className="mt-2 text-xs" style={{ fontFamily: F.body, color: note.ok ? C.green : C.carbon, fontWeight: 600 }}>{note.text}</p>}
      {copyState && copyState !== "copied" && <p className="mt-2 text-xs" style={{ color: C.carbon }}>{copyState}</p>}
    </section>
  );
}

/* Secondary card actions share one quiet chip style; colour goes on the
 * icon (or the text, for the destructive one) so a row of actions doesn't
 * read as a row of alarms. */
const chipClass = "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs disabled:opacity-60";
const chipStyle = (tone = C.ink) => ({ border: `1px solid ${C.rule}`, backgroundColor: C.slip, color: tone, fontFamily: F.body, fontWeight: 600 });

/* Decision filters. Pending and Request Changes can't be read off
 * Rental.status alone (the agreement stays pending_approval in both), so:
 * Pending = the LATEST link is still live and undecided (approval_status is
 * that link's effective status, so an expired or revoked link never counts);
 * Request Changes = open_change_request, set only while the latest link
 * ended in a change request and no newer link or final outcome replaced it.
 * Approved includes agreements that have since gone active on their first
 * paid invoice. */
const DECISION_FILTERS = [
  { key: "pending", label: "Pending", icon: Hourglass, color: C.blue, match: (r) => r.status === "pending_approval" && r.approval_status === "pending" },
  { key: "approved", label: "Approved", icon: CircleCheck, color: C.green, match: (r) => ["approved", "active"].includes(r.status) },
  { key: "rejected", label: "Rejected", icon: CircleX, color: C.carbon, match: (r) => r.status === "rejected" },
  { key: "changes", label: "Request Changes", icon: MessageSquareDiff, color: C.amber, match: (r) => !!r.open_change_request },
];

const POLL_MS = 5000;

function DecisionFilterButton({ filter, count, selected, onClick }) {
  const { icon: Icon, label, color } = filter;
  return (
    // Sized by the toolbar's width (@container), not the viewport -- the
    // sidebar takes a different share of the screen at each breakpoint.
    // Narrow toolbars drop the label (icon + count, label kept for screen
    // readers and as a tooltip); wide ones show it in full.
    <button type="button" onClick={onClick} aria-pressed={selected} aria-label={`${label} (${count})`} title={label}
      className="flex h-9 flex-1 shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-full px-2.5 text-xs transition-shadow hover:shadow-sm @sm:flex-none @3xl:gap-1.5 @3xl:px-3"
      style={{
        fontFamily: F.body, fontWeight: 700,
        color: selected ? C.onAccent : C.ink,
        backgroundColor: selected ? color : C.slip,
        border: `1px solid ${selected ? color : C.rule}`,
        boxShadow: selected ? `0 1px 2px ${color}40` : "none",
      }}>
      <Icon size={13} style={{ color: selected ? C.onAccent : color }} />
      <span className="hidden whitespace-nowrap @3xl:inline">{label}</span>
      <span className="ml-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[10px]"
        style={{ fontFamily: F.mono, fontWeight: 700, color: selected ? color : C.onAccent, backgroundColor: selected ? C.onAccent : color }}>
        {count}
      </span>
    </button>
  );
}

export default function Rentals() {
  const { can } = useSession();
  const [rentals, setRentalsState] = useState(null);
  const [decisionFilter, setDecisionFilter] = useState(null);
  const [search, setSearch] = useState("");
  // Bumped on every local change, so a background poll that started
  // before it can't overwrite the newer data with its older snapshot.
  const localEdits = useRef(0);
  const polling = useRef(false);
  const rentalsRef = useRef(null);
  useEffect(() => { rentalsRef.current = rentals; }, [rentals]);
  const setRentals = useCallback((update) => {
    localEdits.current += 1;
    setRentalsState(update);
  }, []);
  const [staff, setStaff] = useState([]);
  const [parties, setParties] = useState([]);
  const [assets, setAssets] = useState([]);
  const [error, setError] = useState("");
  const [raisingFor, setRaisingFor] = useState(null);
  const [chatWith, setChatWith] = useState(null);
  const [creating, setCreating] = useState(false);
  const [showDevices, setShowDevices] = useState(false);
  const [approvalLink, setApprovalLink] = useState(null);
  const [generatingFor, setGeneratingFor] = useState(null);
  const [historyFor, setHistoryFor] = useState(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [actionError, setActionError] = useState("");
  const [rentalAction, setRentalAction] = useState(null);
  const [flash, setFlash] = useState("");
  const [sendingLinkFor, setSendingLinkFor] = useState(null);
  const [accessLogs, setAccessLogs] = useState({});

  useEffect(() => {
    api.getAll("/rentals/").then(setRentalsState).catch((e) => setError(e.message));
    api.getAll("/users/").then(setStaff);
    // every customer and asset, not just the API's first page of 50 --
    // an asset missing from the picker got re-registered as a "duplicate"
    api.getAll("/parties/").then(setParties);
    api.getAll("/rental-assets/").then(setAssets);
    if (can("portal.manage")) {
      // Latest portal login per party -- shown as a small line under each
      // rental card so staff can see whether the customer has actually
      // used the link/OTP that was sent to them.
      api.get("/portal-access-logs/").then((d) => {
        const latestByParty = {};
        (d.results ?? d).forEach((log) => {
          const existing = latestByParty[log.party];
          if (!existing || new Date(log.created_at) > new Date(existing.created_at)) {
            latestByParty[log.party] = log;
          }
        });
        setAccessLogs(latestByParty);
      });
    }
  }, []);

  useEffect(() => {
    const syncParty = (event) => {
      const { party, id, deleted } = event.detail || {};
      setParties((current) => deleted
        ? current.filter((item) => item.id !== id)
        : party ? [...current.filter((item) => item.id !== party.id), party].sort((a, b) => a.name.localeCompare(b.name)) : current);
    };
    window.addEventListener(PARTY_CHANGED_EVENT, syncParty);
    return () => window.removeEventListener(PARTY_CHANGED_EVENT, syncParty);
  }, []);

  // A customer decides on the public approval link, not here -- re-read the
  // list every few seconds while the tab is visible (and on return to it) so
  // statuses, counts and filters follow without a reload. One request at a
  // time; a failed poll keeps the current list; an unchanged response keeps
  // the same array so nothing re-renders.
  useEffect(() => {
    const poll = async () => {
      if (polling.current || document.hidden) return;
      polling.current = true;
      const startedAt = localEdits.current;
      try {
        const fresh = await api.getAll("/rentals/");
        if (!Array.isArray(fresh) || startedAt !== localEdits.current) return;
        if (rentalsRef.current && JSON.stringify(rentalsRef.current) === JSON.stringify(fresh)) return;
        setRentalsState(fresh);
        // an open approval history re-reads too, so it matches the card
        setHistoryKey((k) => k + 1);
      } catch {
        // transient (offline, deploy, expired session mid-refresh) -- keep
        // showing the last good list and try again on the next tick
      } finally {
        polling.current = false;
      }
    };
    const onVisible = () => { if (!document.hidden) poll(); };
    const timer = setInterval(poll, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, []);

  const decisionCounts = useMemo(() => Object.fromEntries(
    DECISION_FILTERS.map((f) => [f.key, (rentals || []).filter(f.match).length]),
  ), [rentals]);
  const activeFilter = DECISION_FILTERS.find((f) => f.key === decisionFilter);
  // Search runs over the already-loaded list (getAll walks every page), so
  // typing never hits the API; it narrows whatever filter is selected.
  const query = search.trim().toLowerCase();
  const visibleRentals = useMemo(() => {
    if (!rentals) return rentals;
    return rentals.filter((r) => (!activeFilter || activeFilter.match(r)) && (!query
      || (r.party_name || "").toLowerCase().includes(query)
      || (r.agreement_code || "").toLowerCase().includes(query)));
  }, [rentals, activeFilter, query]);
  const narrowed = !!activeFilter || !!query;

  const sendPortalLink = async (partyId, partyName) => {
    setSendingLinkFor(partyId);
    setActionError("");
    try {
      const sent = await api.post("/portal-invites/", { party: partyId });
      const until = sent.invite_expires_at ? new Date(sent.invite_expires_at).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "";
      const wa = sent.whatsapp_delivery?.status;
      const waNote = wa === "sent" ? " WhatsApp: accepted by Meta." : wa === "simulated" ? " WhatsApp: not sent (console mode)." : wa ? ` WhatsApp: not sent${sent.whatsapp_delivery.reason ? ` — ${sent.whatsapp_delivery.reason}` : ""}.` : "";
      setFlash(`Portal link + verification code issued for ${partyName}.${waNote}${until ? ` The link stays valid until ${until}${sent.link_policy === "rental_tenure" ? " (end of rental tenure)" : ""}; each code expires after ${sent.otp_ttl_minutes || 30} minutes.` : ""}`);
      setTimeout(() => setFlash(""), 5000);
    } catch (requestError) {
      setActionError(requestError.body?.detail || requestError.message);
    } finally {
      setSendingLinkFor(null);
    }
  };

  const [handoverFor, setHandoverFor] = useState(null);

  const generateApprovalLink = async (rentalId) => {
    setActionError("");
    setApprovalLink(null); // never leave an older link on screen if this one fails
    setGeneratingFor(rentalId);
    try {
      const result = await api.post(`/rentals/${rentalId}/approval-link/`);
      if (!result?.approval_url) throw new Error("The server did not return an approval link. Try again.");
      setApprovalLink({
        url: result.approval_url, whatsappUrl: result.whatsapp_url || "", expiresAt: result.expires_at,
        hours: result.expires_in_hours, version: result.version, agreementCode: result.rental?.agreement_code,
        rentalId: result.rental?.id ?? rentalId, provider: result.whatsapp_provider,
      });
      if (result.rental) setRentals((list) => list.map((x) => (x.id === result.rental.id ? result.rental : x)));
      setHistoryKey((k) => k + 1);
      window.scrollTo?.({ top: 0, behavior: "smooth" });
    } catch (requestError) {
      const body = requestError.body || {};
      if (body.handover) {
        // say exactly what each device still needs
        const devices = Object.entries(body.devices || {}).map(([device, issues]) => `${device}: ${[].concat(issues).join("; ")}`);
        setActionError(`${[].concat(body.handover).join(" ")} ${devices.join(" | ")}`);
        setHandoverFor(rentalId);
      } else {
        setActionError(body.detail || requestError.message);
      }
    } finally {
      setGeneratingFor(null);
    }
  };

  const refreshRental = async (rentalId) => {
    const fresh = await api.get(`/rentals/${rentalId}/`);
    setRentals((list) => list.map((x) => (x.id === fresh.id ? fresh : x)));
  };

  const patchRental = (rentalId, issue) => {
    setRentals((list) => list.map((r) => {
      if (r.id !== rentalId) return r;
      const exists = r.issues.some((i) => i.id === issue.id);
      const issues = exists ? r.issues.map((i) => (i.id === issue.id ? issue : i)) : [issue, ...r.issues];
      const open_issue_count = issues.filter((i) => i.status !== "Resolved").length;
      return { ...r, issues, open_issue_count };
    }));
  };

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!rentals) return <Spinner label="Loading rentals…" />;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <PageHeader
        title="Rental accounts"
        subtitle="New agreements awaiting action first, then live rentals by churn risk — next payment due and client-raised issues"
        actions={<>
          <PillButton icon={Laptop} onClick={() => setShowDevices(true)}>Devices</PillButton>
          {can("rentals.manage") && <PillButton icon={Plus} primary onClick={() => setCreating(true)}>New rental agreement</PillButton>}
        </>}
      />

      {/* toolbar: live search fills the left, filter buttons sit on the right
          in one unbroken row (click the selected one again to go back to
          every rental). Below ~384px of toolbar the buttons get their own
          full-width row under the search instead of crushing it. */}
      <div className="@container mt-4">
        <div className="flex flex-wrap items-center gap-2 @sm:flex-nowrap @3xl:gap-3">
          <SearchInput value={search} onChange={(e) => setSearch(e.target.value)} onClear={() => setSearch("")}
            placeholder="Search name or agreement code..." className="basis-full @sm:basis-0" />
          <div role="group" aria-label="Filter rentals by approval status" className="flex w-full shrink-0 flex-nowrap gap-1.5 @sm:w-auto @3xl:gap-2">
            {DECISION_FILTERS.map((f) => (
              <DecisionFilterButton key={f.key} filter={f} count={decisionCounts[f.key]} selected={decisionFilter === f.key}
                onClick={() => setDecisionFilter((current) => (current === f.key ? null : f.key))} />
            ))}
          </div>
        </div>
      </div>
      {narrowed && (
        <p className="mt-2 flex flex-wrap items-center justify-end gap-x-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Showing {visibleRentals.length} of {rentals.length} rentals{activeFilter && ` · ${activeFilter.label}`}{query && ` · “${search.trim()}”`}
          <button type="button" onClick={() => { setDecisionFilter(null); setSearch(""); }} className="underline underline-offset-2" style={{ color: C.ink, fontWeight: 600 }}>Show all rentals</button>
        </p>
      )}

      <ErrorNote message={actionError} />
      {flash && <div role="status" className="mt-4 flex items-center gap-2 rounded-xl p-3" style={{ border: `1px solid ${C.green}55`, backgroundColor: `${C.green}10` }}><ShieldCheck size={14} style={{ color: C.green }} /><span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{flash}</span></div>}
      {approvalLink && <ApprovalLinkPanel link={approvalLink} onDismiss={() => setApprovalLink(null)} />}

      <div className="mt-6 space-y-3">
        {visibleRentals.map((r) => {
          const left = r.tenure_months - r.months_paid;
          return (
            <div key={r.id} data-panel className="p-4 sm:p-5" style={{ backgroundColor: C.slip }}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[15px]" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>{r.party_name}</p>
                  <p className="mt-0.5 break-words text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.agreement_code ? `${r.agreement_code} · ${r.rental_type.toUpperCase()} · ` : ""}{r.product_label} · {money(r.total_monthly_fee ?? r.monthly_fee)}/mo</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {r.agreement_code && <Pill color={statusOf(RENTAL_STATUS, r.status).color}>{statusOf(RENTAL_STATUS, r.status).label}</Pill>}
                  {r.agreement_code && r.approval_status !== "not_sent" && !["approved", "active", "closed", "cancelled"].includes(r.status) && (
                    <Pill color={statusOf(APPROVAL_STATUS, r.approval_status).color}>{statusOf(APPROVAL_STATUS, r.approval_status).label}</Pill>
                  )}
                  {r.open_issue_count > 0 && <Pill color={C.carbon}><ShieldAlert size={11} />{r.open_issue_count} open issue{r.open_issue_count !== 1 ? "s" : ""}</Pill>}
                  <Pill color={BAND_COLOR[r.churn_band]}>{r.churn_band} — {r.churn_score}/100</Pill>
                </div>
              </div>

              {r.open_change_request && (
                <button type="button" onClick={() => setHistoryFor(r.id)} className="mt-3 block w-full rounded-xl px-3 py-2.5 text-left" style={{ border: `1px solid ${C.stamp}55`, backgroundColor: `${C.stamp}0d`, fontFamily: F.body }}>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs" style={{ color: C.stamp, fontWeight: 700 }}>
                    <MessageSquareText size={13} /> Customer requested changes (link v{r.open_change_request.version})
                    <span style={{ fontWeight: 400, color: C.inkSoft }}>{fmtDateTime(r.open_change_request.requested_at)} · awaiting staff</span>
                  </span>
                  <span className="mt-1 line-clamp-3 block whitespace-pre-line break-words text-sm" style={{ color: C.ink }}>{r.open_change_request.message}</span>
                </button>
              )}

              {/* next payment -- called out on its own row so it can't be missed */}
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl px-3 py-2" style={{ backgroundColor: r.next_payment_overdue ? `${C.carbon}14` : C.slip2, border: `1px solid ${r.next_payment_overdue ? `${C.carbon}66` : C.rule}` }}>
                <Clock3 size={13} style={{ color: r.next_payment_overdue ? C.carbon : C.inkSoft }} />
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Next recurring payment due</span>
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: r.next_payment_overdue ? C.carbon : C.ink }}>{fmt(r.next_payment_date)}</span>
                {r.next_payment_overdue && <Pill color={C.carbon}>Overdue</Pill>}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 px-1 sm:grid-cols-4">
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Tenure</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{r.months_paid}/{r.tenure_months} mo</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Months left</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{left}</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Late payments</p><p className="text-sm" style={{ fontFamily: F.mono, color: r.late_count ? C.carbon : C.ink }}>{r.late_count}</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Last month paid</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{r.months_paid ? fmt(r.last_payment) : "—"}</p></div>
              </div>

              <RentInvoices rental={r} canRaise={can("rentals.manage")} onChanged={(updated) => setRentals((list) => list.map((x) => (x.id === updated.id ? updated : x)))} />

              {r.lines?.length > 0 && (() => {
                const pending = r.lines.filter((l) => l.handover_issues?.length).length;
                return (
                  <button type="button" onClick={() => setHandoverFor(r.id)} className="mt-3 flex w-full flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-xs"
                    style={{ border: `1px solid ${pending ? `${C.amber}88` : `${C.green}66`}`, backgroundColor: pending ? `${C.amber}10` : `${C.green}10`, fontFamily: F.body, color: C.ink }}>
                    <span className="flex items-center gap-1.5"><Camera size={13} style={{ color: pending ? C.amber : C.green }} />
                      <b>Device handover & warranty</b> — condition, photos, accessories
                    </span>
                    <span style={{ fontWeight: 600, color: pending ? C.amber : C.green }}>
                      {pending ? `${pending} of ${r.lines.length} device${r.lines.length > 1 ? "s" : ""} incomplete` : "Complete"}
                    </span>
                  </button>
                );
              })()}

              <div className="mt-4 flex flex-wrap gap-2 border-t pt-4" style={{ borderColor: C.rule }}>
                <button type="button" onClick={() => setChatWith({ id: r.party, name: r.party_name })} className={chipClass} style={{ backgroundColor: C.green, border: `1px solid ${C.green}`, color: C.onAccent, fontFamily: F.body, fontWeight: 600 }}>
                  <MessageCircle size={13} /> Chat on WhatsApp
                </button>
                {can("rentals.manage") && r.lines?.length > 0 && r.approval_status !== "approved" && !["rejected", "cancelled", "closed"].includes(r.status) && <button type="button" onClick={() => generateApprovalLink(r.id)} disabled={generatingFor === r.id} className={chipClass} style={chipStyle()}><Link2 size={13} style={{ color: C.green }} /> {generatingFor === r.id ? "Generating…" : r.open_change_request ? "Send revised approval link" : "Generate approval link"}</button>}
                {r.agreement_code && <button type="button" onClick={() => setHistoryFor(r.id)} className={chipClass} style={chipStyle()}><History size={13} style={{ color: C.stamp }} /> Approval history</button>}
                {can("rentals.approve") && r.lines?.length > 0 && r.approval_status !== "approved" && !["cancelled", "closed"].includes(r.status) && <button type="button" onClick={() => setRentalAction({ rental: r, action: "approve" })} className={chipClass} style={chipStyle()}><ShieldCheck size={13} style={{ color: C.blue }} /> Approve on behalf</button>}
                <button type="button" onClick={() => setRaisingFor(r.id)} className={chipClass} style={chipStyle()}>
                  <MessageSquarePlus size={13} style={{ color: C.inkSoft }} /> Raise issue
                </button>
                {r.churn_score >= 60 && (
                  <button type="button" className={chipClass} style={chipStyle()}><Phone size={13} style={{ color: C.inkSoft }} />Call customer</button>
                )}
                {can("portal.manage") && (
                  <button type="button" onClick={() => sendPortalLink(r.party, r.party_name)} disabled={sendingLinkFor === r.party} className={chipClass} style={chipStyle()}>
                    <ShieldCheck size={13} style={{ color: C.stamp }} /> {sendingLinkFor === r.party ? "Sending…" : "Send portal link"}
                  </button>
                )}
                {can("rentals.manage") && ["approved", "active"].includes(r.status) && <button type="button" onClick={() => setRentalAction({ rental: r, action: "close" })} className={chipClass} style={chipStyle()}>Close agreement</button>}
                {can("rentals.manage") && ["draft", "pending_approval", "rejected"].includes(r.status) && <button type="button" onClick={() => setRentalAction({ rental: r, action: "cancel" })} className={chipClass} style={chipStyle(C.carbon)}>Cancel agreement</button>}
              </div>

              {can("portal.manage") && accessLogs[r.party] && (
                <p className="mt-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
                  Last portal access: {new Date(accessLogs[r.party].created_at).toLocaleString()} · IP {accessLogs[r.party].ip_address || "unknown"}
                </p>
              )}

              {r.issues.length > 0 && (
                <div className="mt-3 space-y-2">
                  <Eyebrow>Issues raised</Eyebrow>
                  {r.issues.map((issue) => (
                    <IssueRow key={issue.id} issue={issue} staff={staff}
                      onAssigned={(updated) => patchRental(r.id, updated)}
                      onResolved={(updated) => patchRental(r.id, updated)} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {rentals.length > 0 && !visibleRentals.length && narrowed && (
          <p className="rounded-2xl px-4 py-12 text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft, border: `1px dashed ${C.ruleStrong}` }}>
            No matching rental agreements found.{" "}
            <button type="button" onClick={() => { setDecisionFilter(null); setSearch(""); }} className="underline underline-offset-2" style={{ color: C.ink, fontWeight: 600 }}>Show all rentals</button>
          </p>
        )}
        {!rentals.length && <p className="rounded-2xl px-4 py-12 text-center text-sm" style={{ fontFamily: F.body, color: C.inkSoft, border: `1px dashed ${C.ruleStrong}` }}>No rental accounts yet.</p>}
      </div>

      {raisingFor && (
        <RaiseIssueModal rentalId={raisingFor} onClose={() => setRaisingFor(null)}
          onCreated={(issue) => { patchRental(raisingFor, issue); setRaisingFor(null); }} />
      )}
      {showDevices && <RentalDevicesModal assets={assets} canManage={can("rentals.manage")} onClose={() => setShowDevices(false)}
        onChanged={(updated) => setAssets((list) => list.map((a) => (a.id === updated.id ? updated : a)))} />}
      {chatWith && <PartyChatModal partyId={chatWith.id} partyName={chatWith.name} onClose={() => setChatWith(null)} />}
      {rentalAction && <RentalActionModal {...rentalAction} onClose={() => setRentalAction(null)} onCompleted={(updated) => { setRentals((current) => current.map((item) => item.id === updated.id ? updated : item)); setRentalAction(null); api.getAll("/rental-assets/").then(setAssets); }} />}
      {creating && <RentalAgreementModal parties={parties} initialAssets={assets} onClose={() => setCreating(false)} onCreated={(created) => { setRentals((current) => [created, ...current]); setCreating(false); setHandoverFor(created.id); api.getAll("/rental-assets/").then(setAssets); }} />}
      {historyFor && (
        <ApprovalHistoryModal rentalId={historyFor} refreshKey={historyKey} canManage={can("rentals.manage")}
          onClose={() => setHistoryFor(null)}
          onGenerateLink={() => { const id = historyFor; setHistoryFor(null); generateApprovalLink(id); }}
          onOpenHandover={() => { const id = historyFor; setHistoryFor(null); setHandoverFor(id); }} />
      )}
      {handoverFor && rentals.find((x) => x.id === handoverFor) && (
        <DeviceHandoverModal rental={rentals.find((x) => x.id === handoverFor)} onClose={() => setHandoverFor(null)} onChanged={() => refreshRental(handoverFor)} />
      )}
    </div>
  );
}
