import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2, Clock3, Laptop, LogOut, RefreshCw, ShieldCheck,
  Wrench, XCircle,
} from "lucide-react";

import { customerApi } from "../lib/customerApi";
import { C, F, money } from "../lib/theme";

function Notice({ error, children }) {
  return (
    <div className="rounded-md px-3 py-2 text-sm" style={{
      border: `1px solid ${error ? C.carbon : C.green}`,
      color: error ? C.carbon : C.green,
      background: error ? "#fff4f2" : "#effaf5",
    }}>{children}</div>
  );
}

function PortalFrame({ brand = "Vantage Computers", children }) {
  return (
    <div className="min-h-screen px-4 py-6 sm:px-6 sm:py-10" style={{ background: "linear-gradient(135deg, #edf2fc 0%, #f7f9fd 48%, #eef6f5 100%)", color: C.ink }}>
      <div className="mx-auto w-full max-w-6xl">
        <header className="mb-8 flex items-center justify-between sm:mb-10">
          <div>
            <p className="text-xs uppercase" style={{ fontFamily: F.body, color: C.orange, letterSpacing: "0.18em", fontWeight: 700 }}>Customer portal</p>
            <h1 className="mt-1 text-2xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{brand}</h1>
          </div>
          <ShieldCheck size={28} style={{ color: C.stamp }} aria-hidden="true" />
        </header>
        {children}
      </div>
    </div>
  );
}

function AuthCard({ title, subtitle, children }) {
  return (
    <div className="mx-auto max-w-xl overflow-hidden rounded-2xl shadow-xl" style={{ background: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 22px 55px rgba(24, 42, 79, 0.14)" }}>
      <div className="border-b px-6 py-6 sm:px-8 sm:py-7" style={{ borderColor: C.rule, background: "linear-gradient(135deg, #ffffff 0%, #f6f9ff 100%)" }}>
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: `${C.stamp}16`, color: C.stamp }}><ShieldCheck size={22} /></div>
          <div>
            <h2 className="text-[1.65rem] leading-tight sm:text-3xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{title}</h2>
            <p className="mt-2 text-sm leading-6" style={{ color: C.inkSoft }}>{subtitle}</p>
          </div>
        </div>
      </div>
      <div className="px-6 py-6 sm:px-8 sm:py-7">{children}</div>
    </div>
  );
}

function Field({ label, hint, ...props }) {
  return (
    <label className="text-sm" style={{ color: C.ink, display: "block", width: "100%" }}>
      <span className="mb-2 block" style={{ display: "block", fontWeight: 700 }}>{label}</span>
      <input {...props} className="h-12 w-full rounded-lg px-3.5 text-[15px] outline-none transition focus:ring-4" style={{ display: "block", width: "100%", minWidth: 0, border: `1px solid ${C.rule}`, background: C.slip2, boxShadow: "none" }} />
      {hint && <span className="mt-1.5 block text-xs leading-5" style={{ display: "block", color: C.inkSoft }}>{hint}</span>}
    </label>
  );
}

function SubmitButton({ busy, children }) {
  return (
    <button disabled={busy} className="w-full rounded-lg px-4 py-3 text-sm text-white shadow-sm transition hover:brightness-95 disabled:opacity-60" style={{ background: C.stamp, fontWeight: 700 }}>
      {busy ? "Please wait..." : children}
    </button>
  );
}

function Login({ onSignedIn }) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await customerApi.login(phone, password);
      onSignedIn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Welcome back" subtitle="Sign in to view your rental, repair, and approval information securely.">
      {error && <Notice error>{error}</Notice>}
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 20, width: "100%" }}>
        <Field label="Registered mobile number" hint="Enter 10 digits. +91 is added automatically." type="tel" inputMode="numeric" placeholder="98765 43210" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required />
        <Field label="Password" type="password" placeholder="Enter your password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <SubmitButton busy={busy}>Sign in securely</SubmitButton>
      </form>
      <div className="mt-6 rounded-lg px-4 py-3 text-xs leading-5" style={{ background: C.slip2, color: C.inkSoft }}>
        Need access or a password reset? Please contact the service team.
      </div>
    </AuthCard>
  );
}

function SetPassword({ mode, token, onComplete }) {
  const [info, setInfo] = useState(null);
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const route = mode === "activate" ? "activate" : "reset-password";

  useEffect(() => {
    customerApi.tokenInfo(route, token).then(setInfo).catch((err) => setError(err.message));
  }, [route, token]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await customerApi.setPassword(route, token, { phone, password, confirm_password: confirm });
      onComplete();
    } catch (err) {
      const first = Object.values(err.body || {}).find((value) => Array.isArray(value));
      setError(first?.[0] || err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={mode === "activate" ? "Set up your password" : "Reset your password"}
      subtitle="Create secure access to your service dashboard."
    >
      {error && <Notice error>{error}</Notice>}
      {info && <>
        <div className="mb-6 rounded-xl px-4 py-3.5" style={{ background: "#eef5ff", border: "1px solid #cdddf7" }}>
          <p className="text-sm" style={{ fontWeight: 700 }}>{info.customer_name}</p>
          <p className="mt-1 text-xs leading-5" style={{ color: C.inkSoft }}>Secure link expires on {new Date(info.expires_at).toLocaleString()}.</p>
        </div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 20, width: "100%" }}>
        <Field label={`Confirm registered mobile number (${info.phone})`} hint="Enter your 10-digit number. +91 is added automatically." type="tel" inputMode="numeric" placeholder="98765 43210" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required />
        <div style={{ display: "flex", flexDirection: "column", gap: 20, width: "100%" }}>
          <Field label="New password" type="password" placeholder="Minimum 10 characters" autoComplete="new-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
          <Field label="Confirm password" type="password" placeholder="Re-enter password" autoComplete="new-password" minLength={10} value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </div>
        <SubmitButton busy={busy}>{mode === "activate" ? "Activate account" : "Save new password"}</SubmitButton>
        </form>
        <div className="mt-6 flex items-start gap-2 text-xs leading-5" style={{ color: C.inkSoft }}><CheckCircle2 className="mt-0.5 shrink-0" size={14} style={{ color: C.green }} />Use at least 10 characters. This one-time link is not stored in readable form.</div>
      </>}
    </AuthCard>
  );
}

function Status({ value }) {
  const positive = ["active", "approved", "paid", "resolved", "delivered"].includes(String(value).toLowerCase());
  return <span className="rounded-full px-2 py-1 text-xs" style={{ background: positive ? "#e7f8f0" : C.slip2, color: positive ? C.green : C.inkSoft }}>{value}</span>;
}

function Decision({ approval, kind, onDone, disabled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!approval || approval.status !== "pending") return null;

  async function decide(decision) {
    const message = decision === "approve" ? "Approve these final details and charges?" : "Reject this approval request?";
    if (!window.confirm(message)) return;
    setBusy(true); setError("");
    try {
      const payload = { decision, consent: decision === "approve", reason: "" };
      if (kind === "rental") await customerApi.decideRental(approval.id, payload);
      else if (kind === "repair") await customerApi.decideRepair(approval.id, payload);
      else await customerApi.decideRepairOrder(approval.id, payload);
      await onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4">
      {error && <Notice error>{error}</Notice>}
      <div className="mt-2 flex gap-2">
        <button disabled={busy || disabled} onClick={() => decide("approve")} className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm text-white disabled:opacity-50" style={{ background: C.green }}><CheckCircle2 size={15} />Approve</button>
        <button disabled={busy || disabled} onClick={() => decide("reject")} className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm disabled:opacity-50" style={{ border: `1px solid ${C.carbon}`, color: C.carbon }}><XCircle size={15} />Reject</button>
      </div>
    </div>
  );
}

function Dashboard({ initialProfile, onSignedOut }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError("");
    try { setData(await customerApi.dashboard()); } catch (err) { setError(err.message); }
  }
  useEffect(() => {
    let cancelled = false;
    customerApi.dashboard()
      .then((result) => { if (!cancelled) setData(result); })
      .catch((requestError) => { if (!cancelled) setError(requestError.message); });
    return () => { cancelled = true; };
  }, []);

  async function signOut() {
    setBusy(true);
    try { await customerApi.logout(); } finally { onSignedOut(); }
  }

  const profile = data?.profile || initialProfile;
  const pendingCount = useMemo(() => {
    if (!data) return 0;
    return data.rentals.filter((r) => r.approval?.status === "pending").length
      + data.repairs.filter((r) => r.estimate?.approval?.status === "pending").length
      + data.pending_order_approvals.length;
  }, [data]);

  return (
    <PortalFrame brand={profile?.brand?.name}>
      <div className="mb-7 flex flex-wrap items-center justify-between gap-5 rounded-2xl p-5 sm:p-6" style={{ background: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 14px 32px rgba(24, 42, 79, 0.08)" }}>
        <div>
          <p className="text-xs uppercase" style={{ color: C.stamp, fontWeight: 700, letterSpacing: "0.14em" }}>Customer dashboard</p>
          <p className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Welcome, {profile?.name}</p>
          <p className="mt-1 text-sm" style={{ color: C.inkSoft }}>{profile?.parties?.map((p) => p.name).join(", ")} · {profile?.phone}</p>
        </div>
        <div className="flex items-center gap-2">
          <Status value={profile?.access?.mode === "read_only" ? "Read only" : "Active"} />
          <button onClick={load} aria-label="Refresh dashboard" className="rounded-md p-2" style={{ border: `1px solid ${C.rule}` }}><RefreshCw size={15} /></button>
          <button disabled={busy} onClick={signOut} className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }}><LogOut size={15} />Sign out</button>
        </div>
      </div>

      {profile?.access?.mode === "read_only" && <div className="mb-5"><Notice>Your service is complete. Records remain available in read-only mode until {new Date(profile.access.access_until).toLocaleDateString()}.</Notice></div>}
      {error && <div className="mb-5"><Notice error>{error}</Notice></div>}
      {!data && !error && <p>Loading your service records...</p>}
      {data && <div className="space-y-6">
        <section className="grid gap-4 sm:grid-cols-3">
          {[
            [Laptop, "Rentals", data.rentals.length],
            [Wrench, "Repairs", data.repairs.length],
            [Clock3, "Pending approvals", pendingCount],
          ].map(([Icon, label, value]) => <div key={label} className="rounded-2xl p-5" style={{ background: C.slip, border: `1px solid ${C.rule}` }}><Icon size={19} style={{ color: C.stamp }} /><p className="mt-4 text-3xl" style={{ fontFamily: F.display, fontWeight: 700 }}>{value}</p><p className="mt-1 text-sm" style={{ color: C.inkSoft }}>{label}</p></div>)}
        </section>

        <section>
          <div className="mb-3"><p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.12em" }}>Your equipment</p><h2 className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Rentals</h2></div>
          <div className="space-y-3">
            {data.rentals.map((rental) => <article key={rental.id} className="rounded-lg p-4" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
              <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold">{rental.agreement_code}</p><p className="text-xs uppercase" style={{ color: C.inkSoft }}>{rental.rental_type} rental - {rental.tenure_months} months</p></div><Status value={rental.status} /></div>
              <div className="mt-3 space-y-2">{rental.items.map((item, index) => <div key={`${item.asset_tag}-${index}`} className="flex justify-between gap-3 text-sm"><span>{item.brand} {item.model_name} {item.asset_tag && `(${item.asset_tag})`}</span><strong>{money(item.monthly_fee)}/month</strong></div>)}</div>
              <p className="mt-3 text-sm">Combined monthly fee: <strong>{money(rental.total_monthly_fee)}</strong></p>
              <Decision approval={rental.approval} kind="rental" disabled={!profile.access.can_decide} onDone={load} />
            </article>)}
            {!data.rentals.length && <p className="text-sm" style={{ color: C.inkSoft }}>No rental records.</p>}
          </div>
        </section>

        <section>
          <div className="mb-3"><p className="text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 700, letterSpacing: "0.12em" }}>Service updates</p><h2 className="mt-1 text-xl" style={{ fontFamily: F.display, fontWeight: 700 }}>Repairs and service</h2></div>
          <div className="space-y-3">
            {data.repairs.map((repair) => <article key={repair.id} className="rounded-lg p-4" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
              <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold">{repair.code} - {repair.brand} {repair.model_name}</p><p className="text-sm" style={{ color: C.inkSoft }}>{repair.issue}</p></div><Status value={repair.status} /></div>
              {repair.estimate && <div className="mt-3 rounded-md p-3" style={{ background: C.slip2 }}><p className="text-sm font-semibold">Final estimate: {money(repair.estimate.total_amount)}</p>{repair.estimate.lines.map((line, index) => <p key={index} className="mt-1 flex justify-between text-xs"><span>{line.description} x {line.quantity}</span><span>{money(line.line_total)}</span></p>)}<Decision approval={repair.estimate.approval} kind="repair" disabled={!profile.access.can_decide} onDone={load} /></div>}
              <div className="mt-3 flex flex-wrap gap-3 text-xs" style={{ color: C.inkSoft }}>{repair.timeline.map((event, index) => <span key={`${event.type}-${index}`}>{event.label}: {new Date(event.at).toLocaleDateString()}</span>)}</div>
            </article>)}
            {!data.repairs.length && <p className="text-sm" style={{ color: C.inkSoft }}>No repair records.</p>}
          </div>
        </section>

        {data.pending_order_approvals.map((approval) => <section key={approval.id} className="rounded-lg p-4" style={{ background: C.slip, border: `1px solid ${C.rule}` }}>
          <h2 className="font-bold">Combined repair approval - {approval.snapshot?.order_code}</h2>
          <p className="mt-1 text-sm" style={{ color: C.inkSoft }}>Review every device, repair line, and the combined final estimate.</p>
          <div className="mt-3 space-y-3">
            {approval.snapshot?.devices?.map((device) => <div key={device.ticket_code} className="rounded-md p-3" style={{ background: C.slip2 }}>
              <div className="flex flex-wrap justify-between gap-2 text-sm"><strong>{device.ticket_code} - {device.brand} {device.model_name}</strong><strong>{money(device.total_amount)}</strong></div>
              <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>Serial: {device.serial || "Not recorded"} - Issue: {device.reported_issue}</p>
              {device.lines?.map((line, index) => <p key={index} className="mt-1 flex justify-between gap-3 text-xs"><span>{line.description} x {line.quantity}</span><span>{money(line.line_total)}</span></p>)}
            </div>)}
          </div>
          <p className="mt-3 flex justify-between text-sm font-bold"><span>Combined final total</span><span>{money(approval.snapshot?.grand_total || 0)}</span></p>
          {approval.snapshot?.terms && <p className="mt-3 text-xs leading-5" style={{ color: C.inkSoft }}>{approval.snapshot.terms}</p>}
          <Decision approval={approval} kind="repair_order" disabled={!profile.access.can_decide} onDone={load} />
        </section>)}
      </div>}
    </PortalFrame>
  );
}

export default function CustomerPortal({ mode = "login", token = "" }) {
  const [profile, setProfile] = useState(null);
  const [checking, setChecking] = useState(mode === "login" || mode === "dashboard");
  const [route, setRoute] = useState(mode);

  useEffect(() => {
    if (mode !== "login" && mode !== "dashboard") return;
    customerApi.me().then((data) => setProfile(data)).catch(() => setProfile(null)).finally(() => setChecking(false));
  }, [mode]);

  function goLogin() {
    window.history.replaceState({}, "", "/customer/login");
    setProfile(null); setRoute("login"); setChecking(false);
  }
  function signedIn() {
    customerApi.me().then((data) => {
      window.history.replaceState({}, "", "/customer/dashboard");
      setProfile(data); setRoute("dashboard");
    });
  }

  if (checking) return <PortalFrame><p className="text-center">Checking your secure session...</p></PortalFrame>;
  if (route === "activate" || route === "reset") return <PortalFrame><SetPassword mode={route} token={token} onComplete={goLogin} /></PortalFrame>;
  if (profile) return <Dashboard initialProfile={profile} onSignedOut={goLogin} />;
  return <PortalFrame><Login onSignedIn={signedIn} /></PortalFrame>;
}
