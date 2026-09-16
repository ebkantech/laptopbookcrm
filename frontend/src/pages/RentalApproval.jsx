import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileCheck2, LoaderCircle, XCircle } from "lucide-react";

import { api } from "../lib/api";
import { C, F, money } from "../lib/theme";


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
  const unavailable = error && !approval;

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
            {terminal ? (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: approval.status === "approved" ? `${C.green}16` : `${C.carbon}12` }}>
                <CheckCircle2 size={18} style={{ color: approval.status === "approved" ? C.green : C.carbon }} />
                <span className="text-sm">{approval.status === "approved" ? "Your approval has been recorded." : approval.status === "rejected" ? "Your rejection has been recorded." : "This approval link has expired."}</span>
              </div>
            ) : (
              <div className="mt-5 flex items-center gap-2 p-3" style={{ backgroundColor: `${C.amber}16` }}><Clock3 size={17} style={{ color: C.amber }} /><span className="text-xs">This secure link expires in 24 hours.</span></div>
            )}
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="p-3" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Rental type</p><p className="mt-1 text-sm capitalize">{approval.rental_type}</p></div>
              <div className="p-3" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Start date</p><p className="mt-1 text-sm">{approval.start}</p></div>
              <div className="p-3" style={{ backgroundColor: C.slip2 }}><p className="text-xs" style={{ color: C.inkSoft }}>Tenure</p><p className="mt-1 text-sm">{approval.tenure_months} months</p></div>
            </div>
            <div className="mt-5">
              <p className="text-xs uppercase" style={{ color: C.inkSoft }}>Devices and monthly charges</p>
              {approval.items?.map((item) => (
                <div key={item.asset_tag} className="mt-1 flex items-start justify-between gap-3 p-3 text-sm" style={{ backgroundColor: C.slip2 }}>
                  <span><strong>{item.brand} {item.model_name}</strong><span className="mt-1 block text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Asset: {item.asset_tag} · Serial: {item.serial_number}</span></span>
                  <strong className="shrink-0" style={{ fontFamily: F.mono }}>{money(item.monthly_fee)}/mo</strong>
                </div>
              ))}
              <div className="mt-2 flex justify-between p-3" style={{ border: `1px solid ${C.rule}` }}><span>Total monthly charge</span><strong style={{ fontFamily: F.mono }}>{money(approval.total_monthly_fee)}/mo</strong></div>
            </div>
            {approval.terms && <p className="mt-5 text-sm leading-6" style={{ color: C.inkSoft }}>{approval.terms}</p>}
            {!terminal && !choice && (
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                <button onClick={() => setChoice("approve")} className="py-3 text-sm" style={{ backgroundColor: C.green, color: C.onAccent }}><CheckCircle2 className="mr-1 inline" size={16} /> Approve agreement</button>
                <button onClick={() => setChoice("reject")} className="py-3 text-sm" style={{ border: `1px solid ${C.carbon}`, color: C.carbon }}><XCircle className="mr-1 inline" size={16} /> Reject agreement</button>
              </div>
            )}
            {!terminal && choice && (
              <form onSubmit={submit} className="mt-6 p-4" style={{ border: `1px solid ${C.rule}` }}>
                <p className="text-sm" style={{ fontWeight: 700 }}>Confirm {choice}</p>
                {choice === "approve" ? <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> I reviewed the devices, rental duration and monthly charges and authorise this agreement.</label> : <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason (optional)" rows={3} className="mt-3 w-full p-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />}
                <div className="mt-4 flex gap-2"><button type="button" onClick={() => { setChoice(""); setConsent(false); }} className="px-4 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }}>Back</button><button disabled={busy || (choice === "approve" && !consent)} className="px-4 py-2 text-sm" style={{ backgroundColor: choice === "approve" ? C.green : C.carbon, color: C.onAccent, opacity: busy ? 0.6 : 1 }}>{busy ? "Saving…" : "Confirm decision"}</button></div>
              </form>
            )}
            {error && <p className="mt-4 text-sm" style={{ color: C.carbon }}>{error}</p>}
          </article>
        )}
      </div>
    </main>
  );
}
