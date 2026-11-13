import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileCheck2, LoaderCircle, MessageSquareText, XCircle } from "lucide-react";

import { api } from "../lib/api";
import { APP_NAME, C, F, money } from "../lib/theme";

const MAX_MESSAGE = 500;

const CHOICE = {
  approve: { title: "Confirm approval", submit: "Approve bill", color: C.green },
  reject: { title: "Decline the work", submit: "Decline", color: C.carbon },
  request_changes: { title: "Ask for changes", submit: "Send request", color: C.stamp },
};

const OUTCOME = {
  approved: { icon: CheckCircle2, color: C.green, text: "Thank you — your approval is recorded. The technician will now start the work." },
  rejected: { icon: XCircle, color: C.carbon, text: "Your decision is recorded. No repair work will be done. Only the visit charge (if any) will be billed." },
  changes_requested: { icon: MessageSquareText, color: C.stamp, text: "Your request has been sent. Nothing is approved yet — the technician will send a revised bill on a new link." },
  expired: { icon: Clock3, color: C.inkSoft, text: "This approval link has expired. Ask the shop to send a new one." },
  revoked: { icon: AlertCircle, color: C.inkSoft, text: "This link was replaced. Please use the latest link the shop sent you." },
};

const KIND = { visit: "Visit", labour: "Service", part: "Part", product: "Product" };

export default function LeadApproval({ token }) {
  const [approval, setApproval] = useState(null);
  const [choice, setChoice] = useState("");
  const [consent, setConsent] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `/public/lead-approvals/${encodeURIComponent(token)}/`;

  useEffect(() => {
    api.publicGet(endpoint)
      .then(setApproval)
      .catch((e) => setError(e.body?.detail || e.message))
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
    } catch (e) {
      const body = e.body || {};
      setError(body.detail || [].concat(body.reason || body.consent || body.decision || []).join(" ") || e.message);
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
          <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.green }}>{APP_NAME}</p>
          <h1 className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Approve your service bill</h1>
        </header>
        {loading ? (
          <div data-panel className="flex items-center justify-center gap-2 p-10"><LoaderCircle className="animate-spin" size={18} /> Loading your bill…</div>
        ) : unavailable ? (
          <div data-panel className="p-8 text-center"><AlertCircle className="mx-auto" style={{ color: C.carbon }} /><p className="mt-3 text-sm">{error}</p></div>
        ) : approval && (
          <article data-panel className="p-5 sm:p-7">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase" style={{ fontFamily: F.body, color: C.inkSoft }}>On-site service · {approval.lead_code}</p>
                <h2 className="mt-1 text-2xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{money(approval.total)}</h2>
                <p className="mt-1 text-sm" style={{ color: C.inkSoft }}>Hello {approval.customer_name}, please review what the technician found and the charges below.</p>
              </div>
              <FileCheck2 style={{ color: C.green }} />
            </div>
            {terminal && outcome ? (
              <div role="status" className="mt-5 p-3" style={{ backgroundColor: `color-mix(in srgb, ${outcome.color} 8%, transparent)` }}>
                <p className="flex items-start gap-2 text-sm"><outcome.icon size={18} className="mt-0.5 shrink-0" style={{ color: outcome.color }} /><span>{outcome.text}</span></p>
              </div>
            ) : (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: `color-mix(in srgb, ${C.amber} 9%, transparent)` }}><Clock3 size={17} className="shrink-0" style={{ color: C.amber }} /><span className="text-xs">This secure link is valid for 24 hours{expiresAt && ` — until ${expiresAt}`}.</span></div>
            )}
            <dl className="mt-5 grid gap-3 sm:grid-cols-2 text-sm">
              {approval.device && <div className="p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}><dt className="text-xs" style={{ color: C.inkSoft }}>Device</dt><dd className="mt-1">{approval.device}</dd></div>}
              <div className="p-3 rounded-xl" style={{ backgroundColor: C.slip2 }}><dt className="text-xs" style={{ color: C.inkSoft }}>Site</dt><dd className="mt-1 break-words">{approval.site_address}</dd></div>
              <div className="p-3 rounded-xl sm:col-span-2" style={{ backgroundColor: C.slip2 }}><dt className="text-xs" style={{ color: C.inkSoft }}>Problem reported</dt><dd className="mt-1 whitespace-pre-line break-words">{approval.issue}</dd></div>
              {approval.diagnosis && <div className="p-3 rounded-xl sm:col-span-2" style={{ backgroundColor: C.slip2 }}><dt className="text-xs" style={{ color: C.inkSoft }}>What the technician found</dt><dd className="mt-1 whitespace-pre-line break-words">{approval.diagnosis}</dd></div>}
            </dl>
            <div className="mt-5">
              <p className="text-xs uppercase" style={{ color: C.inkSoft }}>Charges</p>
              {approval.lines.map((l, i) => (
                <div key={i} className="mt-2 flex items-start justify-between gap-3 p-3 text-sm rounded-xl" style={{ backgroundColor: C.slip2 }}>
                  <span className="min-w-0"><span className="block break-words">{l.description}</span><span className="text-xs" style={{ color: C.inkSoft }}>{KIND[l.kind] || l.kind}{l.qty > 1 ? ` · ${l.qty} × ${money(l.price)}` : ""}</span></span>
                  <strong className="shrink-0" style={{ fontFamily: F.mono }}>{money(l.amount)}</strong>
                </div>
              ))}
              <div className="mt-2 flex justify-between p-3" style={{ border: `1px solid ${C.rule}` }}><span>Total</span><strong style={{ fontFamily: F.mono }}>{money(approval.total)}</strong></div>
              {approval.note && <p className="mt-3 text-sm" style={{ color: C.inkSoft }}>{approval.note}</p>}
              <p className="mt-3 text-xs" style={{ color: C.inkSoft }}>Work starts only after you approve. If you decline, only the visit charge is billed.</p>
            </div>
            {!terminal && !choice && (
              <div className="mt-6 grid gap-2 sm:grid-cols-3">
                <button onClick={() => setChoice("approve")} className="min-h-[48px] px-3 py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent }}><CheckCircle2 className="mr-1 inline" size={16} /> Approve</button>
                <button onClick={() => setChoice("request_changes")} className="min-h-[48px] px-3 py-3 text-sm" style={{ border: `1px solid ${C.stamp}`, color: C.stamp }}><MessageSquareText className="mr-1 inline" size={16} /> Ask for changes</button>
                <button onClick={() => setChoice("reject")} className="min-h-[48px] px-3 py-3 text-sm" style={{ border: `1px solid ${C.carbon}`, color: C.carbon }}><XCircle className="mr-1 inline" size={16} /> Decline</button>
              </div>
            )}
            {!terminal && choice && (
              <form onSubmit={submit} className="mt-6 p-4" style={{ border: `1px solid ${C.rule}` }}>
                <p className="text-sm" style={{ fontWeight: 700 }}>{CHOICE[choice].title}</p>
                {choice === "approve" && <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 h-4 w-4 shrink-0" /> I have reviewed the diagnosis and the charges of {money(approval.total)}, and I authorise this work.</label>}
                {choice === "request_changes" && <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Tell the technician what should change. Nothing is approved yet — you will get a revised bill on a new link.</p>}
                {choice !== "approve" && (
                  <>
                    <label htmlFor="lead-approval-message" className="sr-only">{needsMessage ? "What would you like changed?" : "Reason"}</label>
                    <textarea id="lead-approval-message" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={MAX_MESSAGE} required={needsMessage}
                      placeholder={needsMessage ? "What would you like changed?" : "Reason (optional)"} rows={4} className="mt-3 w-full p-2 text-base sm:text-sm" style={{ border: `1px solid ${C.rule}` }} />
                    <p className="mt-1 text-right text-xs" style={{ color: C.inkSoft }}>{reason.length}/{MAX_MESSAGE}</p>
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
