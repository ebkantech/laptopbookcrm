import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileCheck2, LoaderCircle, XCircle } from "lucide-react";

import { api } from "../lib/api";
import { C, F, money } from "../lib/theme";


export default function RepairOrderApproval({ token }) {
  const [approval, setApproval] = useState(null);
  const [choice, setChoice] = useState("");
  const [consent, setConsent] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `/public/repair-order-approvals/${encodeURIComponent(token)}/`;

  useEffect(() => {
    api.publicGet(endpoint)
      .then(setApproval)
      .catch((requestError) => setError(requestError.body?.detail || requestError.message))
      .finally(() => setLoading(false));
  }, [endpoint]);

  const submit = async (event) => {
    event.preventDefault();
    if (!choice || (choice === "approve" && !consent)) return;
    setBusy(true);
    setError("");
    try {
      setApproval(await api.publicPost(endpoint, { decision: choice, consent, reason: reason.trim() }));
      setChoice("");
    } catch (requestError) {
      setError(requestError.body?.detail || requestError.message);
    } finally {
      setBusy(false);
    }
  };

  const terminal = ["approved", "rejected", "expired"].includes(approval?.status);

  return (
    <main className="cb-shell min-h-screen px-4 py-8" style={{ color: C.ink }}>
      <div className="mx-auto max-w-3xl">
        <header className="mb-5">
          <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.orange }}>CRMBook</p>
          <h1 className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Secure bulk repair approval</h1>
        </header>
        {loading ? (
          <div data-panel className="flex items-center justify-center gap-2 p-10"><LoaderCircle className="animate-spin" size={18} /> Loading repair order…</div>
        ) : error && !approval ? (
          <div data-panel className="p-8 text-center"><AlertCircle className="mx-auto" style={{ color: C.carbon }} /><p className="mt-3 text-sm">{error}</p></div>
        ) : approval && (
          <article data-panel className="p-5 sm:p-7">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase" style={{ color: C.inkSoft }}>Combined final repair estimate</p>
                <h2 className="mt-1 text-2xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{approval.order_code}</h2>
                <p className="mt-1 text-sm" style={{ color: C.inkSoft }}>Hello {approval.customer?.name}, review every device and charge below.</p>
              </div>
              <FileCheck2 style={{ color: C.green }} />
            </div>

            {terminal ? (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: approval.status === "approved" ? `${C.green}16` : `${C.carbon}12` }}>
                <CheckCircle2 size={18} style={{ color: approval.status === "approved" ? C.green : C.carbon }} />
                <span className="text-sm">{approval.status === "approved" ? "Your combined approval has been recorded." : approval.status === "rejected" ? "Your rejection has been recorded." : "This approval link has expired."}</span>
              </div>
            ) : (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: `${C.amber}16` }}><Clock3 size={17} style={{ color: C.amber }} /><span className="text-xs">This secure link expires in 24 hours.</span></div>
            )}

            <div className="mt-5 space-y-4">
              {approval.devices?.map((device) => (
                <section key={device.ticket_code} className="p-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div><strong>{device.brand} {device.model_name}</strong><p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{device.ticket_code} · Serial: {device.serial}</p></div>
                    <strong style={{ fontFamily: F.mono }}>{money(device.total_amount)}</strong>
                  </div>
                  <p className="mt-3 text-sm"><span style={{ color: C.inkSoft }}>Reported issue: </span>{device.reported_issue}</p>
                  <div className="mt-3 space-y-1">
                    {device.lines?.map((line, index) => (
                      <div key={`${device.ticket_code}-${index}`} className="flex justify-between gap-3 text-sm"><span>{line.description} × {line.quantity}</span><span style={{ fontFamily: F.mono }}>{money(line.line_total)}</span></div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
            <div className="mt-4 flex justify-between p-4" style={{ border: `1px solid ${C.green}` }}><strong>Combined final total</strong><strong style={{ fontFamily: F.mono }}>{money(approval.grand_total)}</strong></div>
            {approval.terms && <p className="mt-5 text-sm leading-6" style={{ color: C.inkSoft }}>{approval.terms}</p>}

            {!terminal && !choice && <div className="mt-6 grid gap-2 sm:grid-cols-2"><button onClick={() => setChoice("approve")} className="py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent }}><CheckCircle2 className="mr-1 inline" size={16} /> Approve all devices</button><button onClick={() => setChoice("reject")} className="py-3 text-sm" style={{ border: `1px solid ${C.carbon}`, color: C.carbon }}><XCircle className="mr-1 inline" size={16} /> Reject order</button></div>}
            {!terminal && choice && <form onSubmit={submit} className="mt-6 p-4" style={{ border: `1px solid ${C.rule}` }}><p className="text-sm" style={{ fontWeight: 700 }}>Confirm {choice}</p>{choice === "approve" ? <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> I reviewed every device, repair line and final cost and authorise the service centre to proceed.</label> : <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason (optional)" rows={3} className="mt-3 w-full p-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />}<div className="mt-4 flex gap-2"><button type="button" onClick={() => { setChoice(""); setConsent(false); }} className="px-4 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }}>Back</button><button disabled={busy || (choice === "approve" && !consent)} className="px-4 py-2 text-sm" style={{ backgroundColor: choice === "approve" ? C.green : C.carbon, color: C.onAccent, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Confirm decision"}</button></div></form>}
            {error && <p className="mt-4 text-sm" style={{ color: C.carbon }}>{error}</p>}
          </article>
        )}
      </div>
    </main>
  );
}
