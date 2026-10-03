import { useState } from "react";
import { AlertTriangle, CheckCircle2, Copy, RefreshCw, Send, Smartphone, XCircle } from "lucide-react";
import { C, F, fmt, money } from "../../lib/theme";
import { api } from "../../lib/api";
import { useSession } from "../../context/SessionContext";
import { ErrorNote, Eyebrow, Pill } from "../Atoms";

const LINK_STATUS_COLOR = { sent: "#F5A623", paid: "#36D399", cancelled: "#8A8F98", failed: "#FB5B5B" };
const spaced = (p) => (p && p.length === 10 ? `${p.slice(0, 5)} ${p.slice(5)}` : p);

/*
 * Collect an invoice over UPI: check the customer's mobile is on UPI
 * (or get another number that is), then text them a UPI-only payment
 * link. The backend re-checks the number and records who sent it.
 */
export default function UpiPaymentLink({ invoice, onChanged }) {
  const { can } = useSession();
  const [check, setCheck] = useState(null); // { phone, status, reason, is_customer_number }
  const [otherPhone, setOtherPhone] = useState("");
  const [askOther, setAskOther] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const links = invoice.payment_links || [];
  const openLink = links.find((l) => l.status === "sent");
  const unpaid = invoice.status !== "Paid";
  const canSend = can("payments.send_link");

  const run = async (label, fn) => {
    setBusy(label);
    setError("");
    setNote("");
    try {
      await fn();
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy("");
    }
  };

  const runCheck = (phone) => run("check", async () => {
    const result = await api.post(`/invoices/${invoice.id}/upi-check/`, phone ? { phone } : {});
    setCheck(result);
    setConfirmed(false);
    setAskOther(result.status === "not_linked");
  });

  const send = () => run("send", async () => {
    const updated = await api.post(`/invoices/${invoice.id}/send-upi-link/`, { phone: check.phone, staff_confirmed_upi: confirmed });
    onChanged(updated);
    setCheck(null);
    setAskOther(false);
    setOtherPhone("");
    setNote(`Payment link sent to ${spaced(check.phone)}.`);
  });

  const refresh = () => run("refresh", async () => {
    const res = await api.post(`/invoices/${invoice.id}/refresh-payment/`);
    onChanged(res.invoice);
    setNote(res.paid ? "Payment received — invoice marked paid." : "Not paid yet.");
  });

  const simulate = () => run("simulate", async () => {
    onChanged(await api.post(`/invoices/${invoice.id}/simulate-payment/`));
    setNote("Sandbox payment recorded — invoice marked paid.");
  });

  if (!links.length && (!unpaid || !canSend)) return null;

  const small = { fontFamily: F.body, color: C.inkSoft };
  const btn = (bg) => ({ backgroundColor: bg, color: C.onAccent, fontFamily: F.body, fontWeight: 600 });

  return (
    <div className="mt-3 p-3" data-panel style={{ border: `1px solid ${C.rule}` }}>
      <Eyebrow>UPI payment link</Eyebrow>

      {unpaid && canSend && !check && (
        <div className="mt-2">
          <p className="text-xs" style={small}>
            {openLink ? "Send a fresh link (the open one will be cancelled)." : "First check the customer's mobile number is linked to UPI."}
          </p>
          <button onClick={() => runCheck()} disabled={!!busy} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={btn(C.stamp)}>
            <Smartphone size={12} /> {busy === "check" ? "Checking…" : "Check customer's number for UPI"}
          </button>
        </div>
      )}

      {check && (
        <div className="mt-2 space-y-2">
          {check.status === "linked" && (
            <p className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, color: C.ink }}>
              <CheckCircle2 size={14} style={{ color: C.green }} /> <b style={{ fontFamily: F.mono }}>{spaced(check.phone)}</b> is linked to UPI
            </p>
          )}
          {check.status === "not_linked" && (
            <p className="flex items-start gap-1.5 text-sm" style={{ fontFamily: F.body, color: C.ink }}>
              <XCircle size={14} className="mt-0.5" style={{ color: C.carbon, flexShrink: 0 }} />
              <span><b style={{ fontFamily: F.mono }}>{spaced(check.phone)}</b> isn't linked to UPI. Ask the customer for a number that has UPI.</span>
            </p>
          )}
          {check.status === "unknown" && (
            <div className="space-y-1.5">
              <p className="flex items-start gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                <AlertTriangle size={13} className="mt-0.5" style={{ color: C.amber, flexShrink: 0 }} /> {check.reason}
              </p>
              <label className="flex items-center gap-2 text-xs" style={{ fontFamily: F.body, color: C.ink }}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                The customer confirmed <b style={{ fontFamily: F.mono }}>{spaced(check.phone)}</b> has UPI
              </label>
            </div>
          )}

          {check.status !== "not_linked" && (
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={send} disabled={!!busy || (check.status === "unknown" && !confirmed)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ ...btn(C.green), opacity: busy || (check.status === "unknown" && !confirmed) ? 0.6 : 1 }}>
                <Send size={12} /> {busy === "send" ? "Sending…" : `Send ${money(invoice.total)} link to ${spaced(check.phone)}`}
              </button>
              {!askOther && <button onClick={() => setAskOther(true)} className="text-xs underline" style={small}>Use another number</button>}
            </div>
          )}

          {askOther && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="block text-xs" style={small}>Another mobile number with UPI
                <input value={otherPhone} onChange={(e) => setOtherPhone(e.target.value.replace(/[^\d+ ]/g, ""))} placeholder="98xxxxxxxx" className="mt-1 block w-44 px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }} />
              </label>
              <button onClick={() => runCheck(otherPhone)} disabled={!!busy || !otherPhone.trim()} className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ ...btn(C.stamp), opacity: busy || !otherPhone.trim() ? 0.6 : 1 }}>
                <Smartphone size={12} /> {busy === "check" ? "Checking…" : "Check"}
              </button>
              <button onClick={() => { setCheck(null); setAskOther(false); }} className="text-xs underline" style={small}>Cancel</button>
            </div>
          )}
        </div>
      )}

      {note && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
      <ErrorNote message={error} />

      {links.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {links.map((l) => (
            <div key={l.id} className="px-2 py-1.5 text-xs" style={{ backgroundColor: C.slip2, fontFamily: F.body, color: C.inkSoft }}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span style={{ fontFamily: F.mono, color: C.ink }}>{money(l.amount)}</span> to <span style={{ fontFamily: F.mono, color: C.ink }}>{l.phone_masked}</span> · sent by <b style={{ color: C.ink }}>{l.sent_by_name}</b> · {fmt(l.created_at)}
                </span>
                <Pill color={LINK_STATUS_COLOR[l.status]}>{l.status}</Pill>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                <span>{l.upi_check_label}</span>
                {l.provider === "sandbox" && <span style={{ color: C.amber }}>· sandbox, no SMS sent</span>}
                {l.status === "sent" && l.provider !== "sandbox" && (
                  <button onClick={() => navigator.clipboard?.writeText(l.url)} className="flex items-center gap-1 underline"><Copy size={10} /> copy link</button>
                )}
                {l.provider_payment_id && <span style={{ fontFamily: F.mono }}>· {l.provider_payment_id}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {unpaid && openLink && (
        <div className="mt-2 flex flex-wrap gap-2">
          {canSend && openLink.provider !== "sandbox" && (
            <button onClick={refresh} disabled={!!busy} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}>
              <RefreshCw size={11} /> {busy === "refresh" ? "Checking…" : "Check payment status"}
            </button>
          )}
          {openLink.provider === "sandbox" && can("invoices.settle") && (
            <button onClick={simulate} disabled={!!busy} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px dashed ${C.amber}`, fontFamily: F.body, color: C.amber }}>
              {busy === "simulate" ? "Simulating…" : "Simulate customer payment (sandbox)"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
