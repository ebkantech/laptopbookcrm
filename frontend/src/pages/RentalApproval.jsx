import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileCheck2, LoaderCircle, MessageSquareText, Package, ShieldCheck, XCircle } from "lucide-react";

import { api } from "../lib/api";
import { C, F, money } from "../lib/theme";

const MAX_MESSAGE = 500;

const CHOICE = {
  approve: { title: "Confirm approval", submit: "Approve agreement", color: C.green },
  reject: { title: "Confirm rejection", submit: "Reject agreement", color: C.carbon },
  request_changes: { title: "Request changes", submit: "Send change request", color: C.stamp },
};

const OUTCOME = {
  approved: { icon: CheckCircle2, color: C.green, text: "Your approval has been recorded." },
  rejected: { icon: XCircle, color: C.carbon, text: "Your rejection has been recorded." },
  changes_requested: { icon: MessageSquareText, color: C.stamp, text: "Your change request has been sent. Nothing has been approved yet — the shop will contact you and send a revised agreement on a new link." },
  expired: { icon: Clock3, color: C.inkSoft, text: "This approval link has expired. Ask the shop to send a new one." },
  revoked: { icon: AlertCircle, color: C.inkSoft, text: "This approval link has been replaced. Please use the latest link the shop sent you." },
};


export default function RentalApproval({ token }) {
  const [approval, setApproval] = useState(null);
  const [choice, setChoice] = useState("");
  const [consent, setConsent] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `/public/rental-approvals/${encodeURIComponent(token)}/`;

  useEffect(() => {
    api.publicGet(endpoint)
      .then(setApproval)
      .catch((requestError) => setError(requestError.body?.detail || requestError.message))
      .finally(() => setLoading(false));
  }, [endpoint]);

  const trimmed = reason.trim();
  const needsMessage = choice === "request_changes";
  const canSubmit = choice && !busy && (choice !== "approve" || consent) && (!needsMessage || (trimmed && trimmed.length <= MAX_MESSAGE));

  const submit = async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      setApproval(await api.publicPost(endpoint, { decision: choice, consent, reason: trimmed }));
      setChoice("");
    } catch (requestError) {
      const body = requestError.body || {};
      setError(body.detail || [].concat(body.reason || body.consent || body.decision || []).join(" ") || requestError.message);
    } finally {
      setBusy(false);
    }
  };

  const terminal = ["approved", "rejected", "expired", "changes_requested", "revoked"].includes(approval?.status);
  const unavailable = error && !approval;
  const outcome = approval && OUTCOME[approval.status];
  const expiresAt = approval?.expires_at
    ? new Date(approval.expires_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <main className="cb-shell min-h-screen px-4 py-8" style={{ color: C.ink }}>
      <div className="mx-auto max-w-2xl">
        <header className="mb-5">
          <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.orange }}>CRMBook</p>
          <h1 className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Secure rental approval</h1>
        </header>
        {loading ? (
          <div data-panel className="flex items-center justify-center gap-2 p-10"><LoaderCircle className="animate-spin" size={18} /> Loading rental agreement…</div>
        ) : unavailable ? (
          <div data-panel className="p-8 text-center"><AlertCircle className="mx-auto" style={{ color: C.carbon }} /><p className="mt-3 text-sm">{error}</p></div>
        ) : approval && (
          <article data-panel className="p-5 sm:p-7">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase" style={{ fontFamily: F.body, color: C.inkSoft }}>Rental agreement</p>
                <h2 className="mt-1 text-2xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{approval.agreement_code}</h2>
                <p className="mt-1 text-sm" style={{ color: C.inkSoft }}>Hello {approval.customer?.name}, please review the devices and monthly charges.</p>
              </div>
              <FileCheck2 style={{ color: C.green }} />
            </div>
            {terminal && outcome ? (
              <div role="status" className="mt-5 p-3" style={{ backgroundColor: `${outcome.color}14` }}>
                <p className="flex items-start gap-2 text-sm">
                  <outcome.icon size={18} className="mt-0.5 shrink-0" style={{ color: outcome.color }} />
                  <span>{outcome.text}</span>
                </p>
                {approval.change_request && (
                  <p className="mt-2 whitespace-pre-line break-words p-2 text-sm" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
                    <span className="block text-xs" style={{ color: C.inkSoft }}>Your message</span>{approval.change_request}
                  </p>
                )}
              </div>
            ) : (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: `${C.amber}16` }}><Clock3 size={17} className="shrink-0" style={{ color: C.amber }} /><span className="text-xs">This secure link is valid for 24 hours{expiresAt && ` — until ${expiresAt}`}.</span></div>
            )}
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Rental type</p><p className="mt-1 text-sm capitalize">{approval.rental_type}</p></div>
              <div className="p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Start date</p><p className="mt-1 text-sm">{approval.start}</p></div>
              <div className="p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Tenure</p><p className="mt-1 text-sm">{approval.tenure_months} months</p></div>
            </div>
            <div className="mt-5">
              <p className="text-xs uppercase" style={{ color: C.inkSoft }}>Devices and monthly charges</p>
              {approval.items?.map((item) => (
                <div key={item.asset_tag} className="mt-2 p-3 text-sm rounded-xl" style={{ backgroundColor: C.slip2 }}>
                  <div className="flex items-start justify-between gap-3">
                    <span><strong>{item.brand} {item.model_name}</strong><span className="mt-1 block text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Asset: {item.asset_tag} · Serial: {item.serial_number}</span></span>
                    <strong className="shrink-0" style={{ fontFamily: F.mono }}>{money(item.monthly_fee)}/mo</strong>
                  </div>
                  <DeviceHandover item={item} token={token} tenure={approval.tenure_months} />
                </div>
              ))}
              <div className="mt-2 flex justify-between p-3" style={{ border: `1px solid ${C.rule}` }}><span>Total monthly charge</span><strong style={{ fontFamily: F.mono }}>{money(approval.total_monthly_fee)}/mo</strong></div>
            </div>
            {approval.terms && <p className="mt-5 text-sm leading-6" style={{ color: C.inkSoft }}>{approval.terms}</p>}
            {!terminal && !choice && (
              <div className="mt-6 grid gap-2 sm:grid-cols-3">
                <button onClick={() => setChoice("approve")} className="min-h-[48px] px-3 py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent }}><CheckCircle2 className="mr-1 inline" size={16} /> Approve</button>
                <button onClick={() => setChoice("request_changes")} className="min-h-[48px] px-3 py-3 text-sm" style={{ border: `1px solid ${C.stamp}`, color: C.stamp }}><MessageSquareText className="mr-1 inline" size={16} /> Request changes</button>
                <button onClick={() => setChoice("reject")} className="min-h-[48px] px-3 py-3 text-sm" style={{ border: `1px solid ${C.carbon}`, color: C.carbon }}><XCircle className="mr-1 inline" size={16} /> Reject</button>
              </div>
            )}
            {!terminal && choice && (
              <form onSubmit={submit} className="mt-6 p-4" style={{ border: `1px solid ${C.rule}` }}>
                <p className="text-sm" style={{ fontWeight: 700 }}>{CHOICE[choice].title}</p>
                {choice === "approve" && <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="mt-1 h-4 w-4 shrink-0" /> I reviewed the devices, their condition and photos, the accessories, the warranty terms, the rental duration and monthly charges, and authorise this agreement.</label>}
                {choice === "request_changes" && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Tell the shop what should change — devices, accessories, dates, or charges. Nothing is approved yet; they will send you a revised agreement on a new link.</p>}
                {choice !== "approve" && (
                  <>
                    <label htmlFor="rental-approval-message" className="sr-only">{needsMessage ? "What would you like changed?" : "Reason"}</label>
                    <textarea id="rental-approval-message" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={MAX_MESSAGE} required={needsMessage}
                      placeholder={needsMessage ? "What would you like changed?" : "Reason (optional)"} rows={4} className="mt-3 w-full p-2 text-base sm:text-sm" style={{ border: `1px solid ${C.rule}` }} />
                    <p className="mt-1 text-right text-xs" style={{ color: reason.length >= MAX_MESSAGE ? C.carbon : C.inkSoft }}>{reason.length}/{MAX_MESSAGE}</p>
                  </>
                )}
                <div className="mt-3 flex flex-col-reverse gap-2 sm:flex-row">
                  <button type="button" onClick={() => { setChoice(""); setConsent(false); setError(""); }} className="min-h-[44px] px-4 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }}>Back</button>
                  <button disabled={!canSubmit} className="min-h-[44px] px-4 py-2 text-sm" style={{ backgroundColor: CHOICE[choice].color, color: C.onAccent, opacity: canSubmit ? 1 : 0.55 }}>{busy ? "Sending…" : CHOICE[choice].submit}</button>
                </div>
              </form>
            )}
            {error && <p className="mt-4 text-sm" style={{ color: C.carbon }}>{error}</p>}
          </article>
        )}
      </div>
    </main>
  );
}


/* What the shop recorded at handover for one device -- shown so the
 * customer approves the condition, accessories and warranty too. */
function DeviceHandover({ item, token, tenure }) {
  if (!item.checks && !item.photos) return null; // approvals sent before handover records existed
  const photoUrl = (id) => api.publicUrl(`/public/rental-approvals/${encodeURIComponent(token)}/photos/${id}/`);
  const warranty = item.warranty || {};
  return (
    <div className="mt-3 space-y-3 border-t pt-3" style={{ borderColor: C.rule }}>
      <div>
        <p className="flex items-center gap-1.5 text-xs" style={{ fontWeight: 700, color: item.working_confirmed ? C.green : C.carbon }}>
          <CheckCircle2 size={13} /> {item.working_confirmed ? "Tested and in working condition at handover" : "Working condition not confirmed"}
          {item.tested_by && <span style={{ fontWeight: 400, color: C.inkSoft }}> · checked by {item.tested_by}</span>}
        </p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs" style={{ color: C.inkSoft }}>
          {(item.checks || []).map((c) => <span key={c.label}>{c.ok ? "✓" : "✗"} {c.label}</span>)}
        </div>
        {item.condition_notes && <p className="mt-1 text-xs"><b>Condition:</b> {item.condition_notes}</p>}
      </div>
      {item.photos?.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
          {item.photos.map((p) => (
            <a key={p.id} href={photoUrl(p.id)} target="_blank" rel="noreferrer" className="block">
              <img src={photoUrl(p.id)} alt={p.label} loading="lazy" className="aspect-[4/3] w-full object-cover" style={{ border: `1px solid ${C.rule}` }} />
              <span className="block truncate text-[11px]" style={{ color: C.inkSoft }}>{p.label}</span>
            </a>
          ))}
        </div>
      )}
      <p className="flex items-start gap-1.5 text-xs">
        <Package size={13} className="mt-0.5 shrink-0" style={{ color: C.inkSoft }} />
        <span><b>Accessories:</b> {item.accessories?.length ? item.accessories.map((a) => a.serial ? `${a.name} (${a.serial})` : a.name).join(", ") : "None — device only"}</span>
      </p>
      <div className="p-2 text-xs" style={{ border: `1px solid ${warranty.included ? C.green : C.rule}` }}>
        <p className="flex items-center gap-1.5" style={{ fontWeight: 700 }}>
          <ShieldCheck size={13} style={{ color: warranty.included ? C.green : C.inkSoft }} />
          {warranty.included ? `Warranty for ${warranty.months || tenure} month${(warranty.months || tenure) > 1 ? "s" : ""} of the rental` : "No warranty on this device"}
        </p>
        {warranty.included && <p className="mt-1 whitespace-pre-line leading-5">{warranty.terms}</p>}
      </div>
    </div>
  );
}
