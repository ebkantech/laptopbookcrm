import { useRef, useState } from "react";
import { CheckCircle2, Circle, Download, FileSignature, Laptop, Upload } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote } from "../Atoms";
import CustomerIdPanel from "../parties/CustomerIdPanel";
import { invoiceStep, kycStep } from "./onboardingModel";

function Step({ done, title, detail }) {
  const Icon = done ? CheckCircle2 : Circle;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon size={15} className="mt-px shrink-0" style={{ color: done ? C.green : C.amber }} aria-hidden="true" />
      <span className="min-w-0 text-xs">
        <b style={{ color: C.ink, fontWeight: 600 }}>{title}</b>
        {detail && <span className="block" style={{ color: C.inkSoft }}>{detail}</span>}
      </span>
    </li>
  );
}

async function save(path, name) {
  const url = await api.blobUrl(path);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/* What this agreement still needs before the device goes out, plus its
 * printable and signed copies. The server enforces the same order
 * (rentals.onboarding); this only shows where things stand. */
export default function RentalOnboarding({ rental, canManage, active, onChanged }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const state = rental.onboarding;
  const code = rental.agreement_code || rental.id;

  const run = async (name, work) => {
    setBusy(name);
    setError("");
    try {
      await work();
    } catch (reason) {
      setError(reason.body?.detail || reason.body?.file?.[0] || reason.message || "That didn't work. Try again.");
    } finally {
      setBusy("");
    }
  };
  const download = () => run("pdf", () => save(`/rentals/${rental.id}/agreement-pdf/`, `${code}-agreement.pdf`));
  const openSigned = () => {
    const ext = (rental.signed_agreement_info?.name || "").split(".").pop();
    run("signed", () => save(`/rentals/${rental.id}/signed-agreement/file/`, `${code}-signed.${ext}`));
  };
  const upload = (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    run("upload", async () => onChanged(await api.upload(`/rentals/${rental.id}/signed-agreement/`, body)));
  };
  const checkout = () => run("checkout", async () => onChanged(await api.post(`/rentals/${rental.id}/checkout/`, {})));
  const reraise = () => run("raise", async () => onChanged(await api.post(`/rentals/${rental.id}/raise-onboarding/`, {})));

  const deposit = state?.required && state.deposit_required ? invoiceStep(state.deposit, "Security deposit") : null;
  const advance = state?.required ? invoiceStep(state.advance, "Advance rent (first month)") : null;
  const kyc = state?.required ? kycStep(state) : [];
  const missingInvoice = state?.required && ((state.deposit_required && !state.deposit) || !state.advance);
  const button = { fontWeight: 600, color: C.ink, border: `1px solid ${C.ruleStrong}`, backgroundColor: C.slip };

  return (
    <section aria-label="Before approval" className="mt-3 rounded-xl p-3" style={{ fontFamily: F.body, border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
      {state?.required && active && (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="m-0 text-xs" style={{ fontWeight: 700, color: C.ink }}>Before device checkout</p>
            <span className="text-[11px]" style={{ fontWeight: 600, color: state.ready_for_checkout ? C.green : C.amber }}>{state.ready_for_checkout ? "Ready for checkout" : `${state.blocking.length} left`}</span>
          </div>
          <ul className="m-0 mt-1 list-none p-0">
            {kyc.map((step) => <Step key={step.title} {...step} />)}
            <Step done={state.approved} title="Customer approval" detail={state.approved ? "Approved" : "Complete the device details, then send the approval link"} />
            {deposit && <Step {...deposit} />}
            {advance && <Step {...advance} />}
          </ul>
          {missingInvoice && canManage && (
            <button type="button" disabled={!!busy} onClick={reraise} className="mt-1 rounded-lg px-3 py-1.5 text-xs disabled:opacity-60" style={button}>Raise the invoice again</button>
          )}
          {!state.paid && <p className="m-0 mt-1 text-[11px]" style={{ color: C.inkSoft }}>Take payment in Sales & Invoices.</p>}
          {!state.kyc_verified && <div className="mt-2"><CustomerIdPanel key={rental.party} partyId={rental.party} canManage={canManage} required onStatus={() => onChanged()} /></div>}
          {canManage && state.approved && !state.checked_out && (
            <button type="button" disabled={!!busy || !state.ready_for_checkout} onClick={checkout} className="mt-2 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs disabled:opacity-50" style={{ fontWeight: 700, color: C.onAccent, backgroundColor: C.green }}>
              <Laptop size={14} /> {busy === "checkout" ? "Checking out…" : "Check out device"}
            </button>
          )}
        </>
      )}
      {state?.required && !active && state.deposit && (
        <p className="m-0 text-xs" style={{ color: C.inkSoft }}>
          Security deposit: <b style={{ color: C.ink }}>{money(state.deposit.total)}</b> ({state.deposit.code}, {state.deposit.status}{state.deposit.refunded ? `, ${money(state.deposit.refunded)} refunded` : ""}). Refund it from Sales & Invoices when the agreement ends.
        </p>
      )}
      <div className={`flex flex-wrap items-center gap-2 ${state?.required ? "mt-2" : ""}`}>
        <button type="button" disabled={!!busy} onClick={download} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs disabled:opacity-60" style={button}><Download size={13} /> {busy === "pdf" ? "Preparing…" : "Download agreement"}</button>
        {canManage && (
          <>
            <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={upload} className="sr-only" aria-label="Signed agreement file" />
            <button type="button" disabled={!!busy} onClick={() => fileRef.current?.click()} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs disabled:opacity-60" style={button}><Upload size={13} /> {busy === "upload" ? "Uploading…" : rental.signed_agreement_info ? "Replace signed copy" : "Upload signed copy"}</button>
          </>
        )}
        {rental.signed_agreement_info && (
          <button type="button" disabled={!!busy} onClick={openSigned} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs disabled:opacity-60" style={{ fontWeight: 600, color: C.green }}>
            <FileSignature size={13} /> Signed copy · {fmt(rental.signed_agreement_info.uploaded_at)}
          </button>
        )}
      </div>
      <ErrorNote message={error} />
    </section>
  );
}
