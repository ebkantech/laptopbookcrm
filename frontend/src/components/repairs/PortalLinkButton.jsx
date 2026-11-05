import { useState } from "react";
import { ShieldCheck } from "lucide-react";

import { ErrorNote } from "../Atoms";
import { useSession } from "../../context/SessionContext";
import { api } from "../../lib/api";
import { announcePartyChanged } from "../../lib/partyEvents";
import { C, F } from "../../lib/theme";
import { whatsappSendNote } from "../../lib/whatsappDelivery";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Sends the repair customer their portal link and emailed sign-in code. Rental
// accounts need a running agreement, which the server explains if there isn't
// one. Older customers can have no email, so it can be added right here.
export default function PortalLinkButton({ partyId, partyName }) {
  const { can } = useSession();
  const [busy, setBusy] = useState(false);
  const [needsEmail, setNeedsEmail] = useState(false);
  const [email, setEmail] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const send = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.post("/portal-invites/", { party: partyId }));
      setNeedsEmail(false);
    } catch (requestError) {
      const detail = requestError.body?.detail || requestError.message;
      const missing = /add an email address/i.test(detail);
      setNeedsEmail(missing);
      setError(missing && can("parties.edit") ? "" : detail);
    } finally {
      setBusy(false);
    }
  };
  const saveAndSend = async () => {
    const cleaned = email.trim();
    if (!EMAIL_RE.test(cleaned)) { setError("Enter a valid email address."); return; }
    setBusy(true);
    setError("");
    try {
      announcePartyChanged(await api.patch(`/parties/${partyId}/`, { email: cleaned }));
    } catch (requestError) {
      setError(requestError.body?.email?.[0] || requestError.body?.detail || requestError.message);
      setBusy(false);
      return;
    }
    await send();
  };
  const until = result?.invite_expires_at ? new Date(result.invite_expires_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  const delivery = result?.whatsapp_delivery;
  const whatsapp = delivery?.status === "simulated" ? { text: "WhatsApp API isn't switched on, so the link went by email only." } : whatsappSendNote(delivery);
  return (
    <div className="mt-4">
      <button type="button" onClick={send} disabled={busy} className="flex w-full items-center justify-center gap-1.5 py-2 text-xs disabled:opacity-60" style={{ border: `1px solid ${C.rule}`, color: C.ink }}>
        <ShieldCheck size={13} style={{ color: C.stamp }} /> {busy ? "Sending…" : "Send portal link"}
      </button>
      {needsEmail && can("parties.edit") && (
        <div className="mt-2">
          <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{partyName} has no email address. The sign-in code goes by email, so add one to send the link.</p>
          <div className="mt-2 flex gap-2">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="customer@example.com" aria-label="Customer email" className="min-w-0 flex-1 px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip, color: C.ink }} />
            <button type="button" onClick={saveAndSend} disabled={busy || !email.trim()} className="shrink-0 px-3 py-1.5 text-xs disabled:opacity-60" style={{ backgroundColor: C.green, color: C.onAccent }}>{busy ? "Sending…" : "Save and send"}</button>
          </div>
        </div>
      )}
      {result && (
        <p role="status" className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Portal link and sign-in code issued for {partyName}{result?.link_policy === "repair_job" ? ", valid until the job is delivered" : until ? `, valid until ${until}` : ""}. Copy them from Chat on WhatsApp.{whatsapp ? ` ${whatsapp.text}` : ""}
        </p>
      )}
      <ErrorNote message={error} />
    </div>
  );
}
