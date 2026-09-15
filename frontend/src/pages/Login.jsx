import { useState } from "react";
import { Lock, LogIn } from "lucide-react";
import { C, F } from "../lib/theme";
import { useSession } from "../context/SessionContext";

export default function Login() {
  const { login } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
    } catch {
      setError("Invalid username or password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cb-shell flex h-screen w-full items-center justify-center">
      <form onSubmit={submit} data-panel className="w-full max-w-sm p-8" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <div className="flex items-center gap-2">
          <Lock size={16} style={{ color: C.stamp }} />
          <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.18em", color: C.orange }}>CRMBook</span>
        </div>
        <p className="mt-3 text-lg" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>Sign in</p>
        <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Use a seeded account, e.g. aman.kapoor / crmbook123.</p>

        <label className="mt-5 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} autoFocus />
        </label>
        <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        {error && <p className="mt-3 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>{error}</p>}

        <button type="submit" disabled={busy} className="mt-5 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <LogIn size={13} /> {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
