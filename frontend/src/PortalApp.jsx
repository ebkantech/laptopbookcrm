import { useEffect, useState } from "react";
import {
  ShieldCheck, LogOut, Wrench, FileText, Star, Repeat2, Clock3, MapPin,
} from "lucide-react";
import { C, F, fmt, money, APP_NAME, APP_VERSION } from "./lib/theme";
import { portalApi } from "./lib/portalApi";

/* ------------------------------------------------------------------ *
 *  Login -- a portal link (/portal/<token>) plus the OTP sent
 *  separately to the customer's phone. Two different channels, so
 *  someone with only the link (e.g. it leaked over shared WhatsApp)
 *  still can't get in without the phone too.
 * ------------------------------------------------------------------ */
function PortalLogin({ token, onLoggedIn }) {
  const [status, setStatus] = useState("checking"); // checking | ready | invalid
  const [info, setInfo] = useState(null);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    portalApi.inviteStatus(token)
      .then((d) => { setInfo(d); setStatus("ready"); })
      .catch((e) => { setError(e.message); setStatus("invalid"); });
  }, [token]);

  const submit = async () => {
    if (!otp.trim()) return setError("Enter the 6-digit code.");
    setBusy(true);
    setError("");
    try {
      const d = await portalApi.verify(token, otp.trim());
      portalApi.setSession(d.portal_token);
      onLoggedIn(d.party, d.access_log_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen w-full items-center justify-center" style={{ backgroundColor: C.paper }}>
      <div className="w-full max-w-sm p-8" style={{ border: `2px solid ${C.ruleStrong}`, backgroundColor: C.slip, boxShadow: "0 12px 32px rgba(0,0,0,0.5)" }}>
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} style={{ color: C.stamp }} />
          <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.18em", color: C.orange }}>{APP_NAME} {APP_VERSION}</span>
        </div>
        <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Vantage Computers</p>
        <p className="mt-3 text-lg" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>Your rental portal</p>

        {status === "checking" && <p className="mt-4 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Checking your link\u2026</p>}

        {status === "invalid" && (
          <div className="mt-4 px-3 py-2" style={{ backgroundColor: `${C.carbon}14`, border: `1px solid ${C.carbon}` }}>
            <p className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{error || "This link is no longer valid."}</p>
            <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Ask us for a new one over WhatsApp.</p>
          </div>
        )}

        {status === "ready" && (
          <>
            <p className="mt-3 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
              Hi {info.party_name}, enter the code we sent to your phone ending in {info.masked_phone}.
            </p>
            <input
              value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="6-digit code" autoFocus
              className="mt-4 w-full bg-transparent px-3 py-2 text-center text-lg outline-none"
              style={{ fontFamily: F.mono, letterSpacing: "0.3em", color: C.ink, border: `1px solid ${C.rule}` }}
            />
            {error && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>{error}</p>}
            <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
              {busy ? "Verifying\u2026" : "Verify & enter"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function LocationPrompt({ accessLogId }) {
  const [state, setState] = useState("idle"); // idle | asking | shared | declined | unsupported

  const share = () => {
    if (!navigator.geolocation) return setState("unsupported");
    setState("asking");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await portalApi.post("/portal/location/", {
            access_log_id: accessLogId,
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          });
          setState("shared");
        } catch {
          setState("declined");
        }
      },
      () => setState("declined"), // customer said no in the browser's own prompt
      { timeout: 10000 },
    );
  };

  if (state === "shared") return null; // done, don't keep nagging
  if (!accessLogId) return null;

  return (
    <div className="mt-4 flex items-center justify-between gap-3 px-4 py-3" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
      <div className="flex items-center gap-2">
        <MapPin size={14} style={{ color: C.inkSoft }} />
        <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          {state === "declined" ? "No problem \u2014 you can share this anytime." : "Optional: share your location to help us verify your device pickup."}
        </span>
      </div>
      {state !== "declined" && (
        <button onClick={share} disabled={state === "asking"} className="shrink-0 px-3 py-1.5 text-xs uppercase" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontFamily: F.body, fontWeight: 600 }}>
          {state === "asking" ? "Asking\u2026" : "Share location"}
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ * Dashboard */
function Section({ title, icon: Icon, children }) {
  return (
    <div className="mt-4 p-4" style={{ border: `2px solid ${C.rule}`, backgroundColor: C.slip, boxShadow: "0 4px 14px rgba(0,0,0,0.35)" }}>
      <p className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}><Icon size={14} style={{ color: C.stamp }} />{title}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function FeedbackForm({ onSubmitted }) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await portalApi.post("/portal/feedback/", { rating, comment: comment.trim() });
      setSent(true);
      onSubmitted?.();
    } finally {
      setBusy(false);
    }
  };

  if (sent) return <p className="text-sm" style={{ fontFamily: F.body, color: C.green }}>Thanks for letting us know!</p>;

  return (
    <div>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} onClick={() => setRating(n)}>
            <Star size={22} fill={n <= rating ? C.amber : "none"} style={{ color: C.amber }} />
          </button>
        ))}
      </div>
      <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="Anything you'd like us to know? (optional)"
        className="mt-2 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
      <button onClick={submit} disabled={busy} className="mt-2 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, opacity: busy ? 0.7 : 1 }}>
        {busy ? "Sending\u2026" : "Send feedback"}
      </button>
    </div>
  );
}

function PortalDashboard({ party, accessLogId, onLogout }) {
  const [rentals, setRentals] = useState(null);
  const [invoices, setInvoices] = useState(null);
  const [repairs, setRepairs] = useState(null);
  const [warranties, setWarranties] = useState(null);

  useEffect(() => {
    portalApi.get("/portal/rentals/").then(setRentals);
    portalApi.get("/portal/invoices/").then(setInvoices);
    portalApi.get("/portal/repairs/").then(setRepairs);
    portalApi.get("/portal/warranties/").then(setWarranties);
  }, []);

  return (
    <div className="min-h-screen" style={{ backgroundColor: C.paper }}>
      <header className="flex items-center justify-between px-5 py-4" style={{ borderBottom: `1px solid ${C.rule}`, backgroundColor: C.deep }}>
        <div>
          <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.orange }}>{APP_NAME} {APP_VERSION}</p>
          <p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>Hi, {party.name}</p>
        </div>
        <button onClick={onLogout} className="flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}><LogOut size={13} /> Sign out</button>
      </header>

      <div className="mx-auto max-w-lg px-5 py-6">
        <LocationPrompt accessLogId={accessLogId} />

        <Section title="Your rental" icon={Repeat2}>
          {!rentals ? <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading\u2026</p> : rentals.length ? rentals.map((r) => (
            <div key={r.id} className="mb-2 px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.product_label}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{money(r.monthly_fee)}/mo \u00b7 {r.months_paid}/{r.tenure_months} months paid</p>
              <p className="mt-1 flex items-center gap-1 text-xs" style={{ fontFamily: F.mono, color: r.next_payment_overdue ? C.carbon : C.inkSoft }}>
                <Clock3 size={11} /> Next payment: {fmt(r.next_payment_date)} {r.next_payment_overdue && "(overdue)"}
              </p>
            </div>
          )) : <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No active rental on file.</p>}
        </Section>

        <Section title="Invoices" icon={FileText}>
          {!invoices ? <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading\u2026</p> : invoices.length ? invoices.map((i) => (
            <div key={i.id} className="mb-1.5 flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <span className="text-xs" style={{ fontFamily: F.mono, color: C.ink }}>{i.code} \u00b7 {fmt(i.date)}</span>
              <span className="text-xs" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(i.total)} \u00b7 {i.status}</span>
            </div>
          )) : <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No invoices yet.</p>}
        </Section>

        <Section title="Repairs" icon={Wrench}>
          {!repairs ? <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading\u2026</p> : repairs.tickets.length ? repairs.tickets.map((t) => (
            <div key={t.id} className="mb-1.5 px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.ink }}>{t.code} \u00b7 {t.brand} {t.model_name} \u00b7 {t.status}</p>
            </div>
          )) : <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No repair tickets on file.</p>}
        </Section>

        <Section title="Warranty" icon={ShieldCheck}>
          {!warranties ? <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading\u2026</p> : warranties.length ? warranties.map((w) => (
            <div key={w.id} className="mb-1.5 px-3 py-2" style={{ backgroundColor: C.slip2 }}>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{w.item_label}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{fmt(w.start_date)} \u2192 {fmt(w.end_date)} \u00b7 {w.status}</p>
            </div>
          )) : <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No warranty on file.</p>}
        </Section>

        <Section title="Leave feedback" icon={Star}>
          <FeedbackForm />
        </Section>
      </div>
    </div>
  );
}

export default function PortalApp({ token }) {
  const [party, setParty] = useState(undefined); // undefined = checking, null = need login
  const [accessLogId, setAccessLogId] = useState(null);

  useEffect(() => {
    if (portalApi.hasSession()) {
      // returning session (not a fresh link click) -- no new access
      // log entry gets created here, since that only happens at the
      // actual OTP-verify moment; a resumed session has nothing fresh
      // to log beyond what verify() already captured
      portalApi.get("/portal/me/").then(setParty).catch(() => { portalApi.clearSession(); setParty(null); });
    } else {
      setParty(null);
    }
  }, []);

  const logout = () => { portalApi.clearSession(); setParty(null); setAccessLogId(null); };
  const onLoggedIn = (p, logId) => { setParty(p); setAccessLogId(logId); };

  if (party === undefined) return <div className="flex h-screen items-center justify-center" style={{ backgroundColor: C.paper }} />;
  if (party) return <PortalDashboard party={party} accessLogId={accessLogId} onLogout={logout} />;
  if (!token) {
    return (
      <div className="flex h-screen w-full items-center justify-center px-6 text-center" style={{ backgroundColor: C.paper }}>
        <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Your session has ended. Please use the link we sent you to sign back in.</p>
      </div>
    );
  }
  return <PortalLogin token={token} onLoggedIn={onLoggedIn} />;
}
