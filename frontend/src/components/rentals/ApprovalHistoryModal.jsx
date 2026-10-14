import { useEffect, useState } from "react";
import {
  Ban, Camera, CheckCircle2, Clock3, FilePlus2, Link2, Loader2, MessageSquareText, PencilLine, ShieldCheck, X, XCircle,
} from "lucide-react";

import { api } from "../../lib/api";
import { C, F, money } from "../../lib/theme";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";
import { APPROVAL_STATUS, RENTAL_STATUS, fmtDateTime, statusOf } from "./approvalStatus";

const SOURCE_LABEL = { customer: "Customer via secure link", admin: "Admin on behalf of customer", superadmin: "Super Admin override" };

/* What one audit event means, in staff language. */
function describe(event) {
  const m = event.metadata || {};
  const v = event.approval_version ? `v${event.approval_version}` : "";
  switch (event.type) {
    case "agreement_created":
      return { icon: FilePlus2, color: C.inkSoft, title: "Agreement created", detail: m.line_count ? `${m.line_count} device${m.line_count > 1 ? "s" : ""}` : "" };
    case "approval_link_created":
      return {
        icon: Link2, color: C.stamp,
        title: m.responds_to_change_request_version ? `New approval link ${v} generated` : `Approval link ${v} created`,
        detail: [
          m.responds_to_change_request_version && `Revised agreement in response to the change request on v${m.responds_to_change_request_version}`,
          m.expires_at && `Valid until ${fmtDateTime(m.expires_at)}`,
        ].filter(Boolean).join(" · "),
      };
    case "changes_requested":
      return { icon: MessageSquareText, color: C.stamp, title: `Customer requested changes on ${v}`, quote: m.message, detail: "Via the secure approval link" };
    case "approval_decided": {
      const approved = m.decision === "approved";
      return {
        icon: approved ? CheckCircle2 : XCircle, color: approved ? C.green : C.carbon,
        title: `${approved ? "Approved" : "Rejected"}${v ? ` (${v})` : ""}`,
        detail: SOURCE_LABEL[m.source] || "", quote: m.reason,
      };
    }
    case "approval_link_expired":
      return { icon: Clock3, color: C.inkSoft, title: `Approval link ${v} expired`, detail: "No response before the link ran out" };
    case "handover_updated":
      return {
        icon: Camera, color: C.amber, title: "Staff updated the device handover",
        detail: [m.what, m.pending_link_revoked && "the open approval link was revoked"].filter(Boolean).join(" — "),
      };
    case "modified_after_approval":
      return { icon: PencilLine, color: C.amber, title: "Staff modified the agreement after approval", quote: m.reason };
    case "agreement_cancelled":
      return { icon: Ban, color: C.carbon, title: "Agreement cancelled", quote: m.reason };
    case "agreement_closed":
      return { icon: ShieldCheck, color: C.inkSoft, title: "Agreement closed", quote: m.reason };
    default:
      return { icon: Clock3, color: C.inkSoft, title: event.label };
  }
}

function LinkVersion({ approval }) {
  const status = statusOf(APPROVAL_STATUS, approval.status);
  const cr = approval.change_request;
  const responded = approval.decided_at && ["approved", "rejected", "changes_requested"].includes(approval.status);
  return (
    <div className="rounded-xl p-3" style={{ border: `1px solid ${cr?.open ? `${C.stamp}66` : C.rule}`, backgroundColor: C.slip }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>
          Link v{approval.version}
          {approval.total_monthly_fee != null && <span className="ml-2 text-xs" style={{ fontFamily: F.mono, fontWeight: 400, color: C.inkSoft }}>{money(approval.total_monthly_fee)}/mo · {approval.item_count} device{approval.item_count !== 1 ? "s" : ""}</span>}
        </p>
        <Pill color={status.color}>{status.label}</Pill>
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2" style={{ fontFamily: F.body }}>
        <div className="flex gap-1.5"><dt style={{ color: C.inkSoft }}>Created</dt><dd className="m-0" style={{ color: C.ink }}>{fmtDateTime(approval.created_at)}{approval.requested_by && ` by ${approval.requested_by}`}</dd></div>
        {approval.expires_at && <div className="flex gap-1.5"><dt style={{ color: C.inkSoft }}>Expires</dt><dd className="m-0" style={{ color: C.ink }}>{fmtDateTime(approval.expires_at)}</dd></div>}
        {responded && <div className="flex gap-1.5"><dt style={{ color: C.inkSoft }}>Response</dt><dd className="m-0" style={{ color: C.ink }}>{fmtDateTime(approval.decided_at)}</dd></div>}
        {approval.source && <div className="flex gap-1.5"><dt style={{ color: C.inkSoft }}>Source</dt><dd className="m-0" style={{ color: C.ink }}>{approval.source_label}{approval.decided_by && ` (${approval.decided_by})`}</dd></div>}
      </dl>
      {approval.reason && (
        <blockquote className="mb-0 mt-2 whitespace-pre-line break-words rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: C.slip2, borderLeft: `3px solid ${status.color}`, color: C.ink, fontFamily: F.body }}>
          {approval.reason}
        </blockquote>
      )}
      {cr && (
        <p className="mt-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: cr.open ? C.stamp : C.green }}>
          {cr.open ? "Open — waiting for staff to revise the agreement and send a new link" : cr.answered_by_version ? `Answered with link v${cr.answered_by_version}` : "Closed — the agreement is no longer awaiting approval"}
        </p>
      )}
      {approval.decided_ip && (
        <p className="mt-1 break-all text-[11px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>
          IP {approval.decided_ip}{approval.decided_user_agent && ` · ${approval.decided_user_agent}`}
        </p>
      )}
    </div>
  );
}

export default function ApprovalHistoryModal({ rentalId, canManage, onClose, onGenerateLink, onOpenHandover, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.get(`/rentals/${rentalId}/approval-history/`)
      .then((d) => { if (!cancelled) { setData(d); setError(""); } })
      .catch((e) => { if (!cancelled) setError(e.body?.detail || e.message); });
    return () => { cancelled = true; };
  }, [rentalId, refreshKey]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rentalStatus = data && statusOf(RENTAL_STATUS, data.rental.status);
  const open = data?.open_change_request;
  const canRevise = canManage && data && ["draft", "pending_approval"].includes(data.rental.status);

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-center sm:p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="approval-history-title" data-panel
        className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl sm:rounded-2xl"
        style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-3 border-b px-4 py-3 sm:px-6 sm:py-4" style={{ borderColor: C.rule }}>
          <div className="min-w-0">
            <Eyebrow>Approval history</Eyebrow>
            <h2 id="approval-history-title" className="mt-1 break-words text-base" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>
              {data ? `${data.rental.agreement_code || `Rental #${data.rental.id}`} · ${data.rental.party_name}` : "Loading…"}
            </h2>
            {rentalStatus && <div className="mt-1.5"><Pill color={rentalStatus.color}>Agreement: {rentalStatus.label}</Pill></div>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          <ErrorNote message={error} />
          {!data && !error && <div className="flex items-center justify-center gap-2 py-10 text-sm" style={{ color: C.inkSoft }}><Loader2 size={16} className="animate-spin" /> Loading history…</div>}

          {data && (
            <>
              {open && (
                <section className="rounded-xl p-3 sm:p-4" style={{ border: `1px solid ${C.stamp}55`, backgroundColor: `${C.stamp}0d` }}>
                  <p className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.stamp }}>
                    <MessageSquareText size={15} /> Customer requested changes on link v{open.version}
                  </p>
                  <p className="mt-0.5 text-xs" style={{ color: C.inkSoft }}>{fmtDateTime(open.requested_at)} · not yet resolved</p>
                  <blockquote className="mb-0 mt-2 whitespace-pre-line break-words rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: C.slip, color: C.ink, fontFamily: F.body }}>{open.message}</blockquote>
                  <p className="mt-2 text-xs" style={{ color: C.inkSoft }}>The agreement is still awaiting approval and its devices stay reserved. Update the handover if needed, then send a new link — the customer approves the revised version.</p>
                  {canRevise && (
                    <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                      {onOpenHandover && <button type="button" onClick={onOpenHandover} className="flex min-h-[40px] items-center justify-center gap-1.5 rounded-full px-4 text-xs" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, color: C.ink, fontWeight: 600 }}><Camera size={13} /> Update device handover</button>}
                      <button type="button" onClick={onGenerateLink} className="flex min-h-[40px] items-center justify-center gap-1.5 rounded-full px-4 text-xs" style={{ backgroundColor: C.stamp, color: C.onAccent, fontWeight: 600 }}><Link2 size={13} /> Send revised approval link</button>
                    </div>
                  )}
                </section>
              )}

              <section className="mt-4 first:mt-0">
                <Eyebrow>Approval links</Eyebrow>
                <div className="mt-2 space-y-2">
                  {data.approvals.map((a) => <LinkVersion key={a.id} approval={a} />)}
                  {!data.approvals.length && <p className="rounded-xl px-3 py-6 text-center text-sm" style={{ color: C.inkSoft, border: `1px dashed ${C.ruleStrong}` }}>No approval link has been generated yet.</p>}
                </div>
              </section>

              <section className="mt-5">
                <Eyebrow>Activity</Eyebrow>
                <ol className="mt-2 list-none p-0">
                  {data.timeline.map((event, i) => {
                    const d = describe(event);
                    const Icon = d.icon;
                    const last = i === data.timeline.length - 1;
                    return (
                      <li key={event.id} className="relative flex gap-3 pb-4">
                        {!last && <span aria-hidden className="absolute left-[13px] top-7 bottom-0 w-px" style={{ backgroundColor: C.rule }} />}
                        <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full" style={{ backgroundColor: `${d.color}16`, color: d.color }}><Icon size={14} /></span>
                        <div className="min-w-0 flex-1 pt-0.5">
                          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{d.title}</p>
                          <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                            {fmtDateTime(event.at)}{event.actor ? ` · ${event.actor}` : event.type === "changes_requested" || (event.type === "approval_decided" && event.metadata?.source === "customer") ? " · Customer" : ""}
                          </p>
                          {d.detail && <p className="mt-0.5 break-words text-xs" style={{ color: C.inkSoft }}>{d.detail}</p>}
                          {d.quote && <p className="mt-1 whitespace-pre-line break-words rounded-lg px-2.5 py-1.5 text-sm" style={{ backgroundColor: C.slip2, color: C.ink }}>{d.quote}</p>}
                        </div>
                      </li>
                    );
                  })}
                  {!data.timeline.length && <li className="text-sm" style={{ color: C.inkSoft }}>No activity recorded.</li>}
                </ol>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
