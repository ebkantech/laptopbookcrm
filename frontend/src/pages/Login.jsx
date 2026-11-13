import { useState } from "react";
import {
  Boxes,
  Eye,
  EyeOff,
  Lock,
  LogIn,
  Repeat2,
  Wrench,
} from "lucide-react";

import { C, F, APP_NAME, APP_VERSION } from "../lib/theme";
import BrandMark from "../components/shell/BrandMark";
import { useSession } from "../context/SessionContext";

// What the app actually covers -- shown beside the form on wide screens.
const MODULES = [
  {
    icon: Boxes,
    title: "Shared inventory",
    text: "Stock across every shop and online channel, with rack locations and barcode labels.",
  },
  {
    icon: Wrench,
    title: "Repairs & service",
    text: "Tickets from intake to delivery, customer-approved estimates and repair billing.",
  },
  {
    icon: Repeat2,
    title: "Rentals",
    text: "Agreements, device handover, recurring invoices and churn risk in one place.",
  },
];

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <BrandMark size={44} />
      <div>
        <p className="text-[21px] leading-none" style={{ fontFamily: F.editorial, fontWeight: 600, color: C.navInk }}>
          Vantage<span style={{ color: C.cta }}>2x</span>
        </p>
        <p className="mt-1.5 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: C.navInkSoft }}>
          {APP_VERSION}
        </p>
      </div>
    </div>
  );
}

export default function Login() {
  const { login } = useSession();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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

  const fieldClass =
    "mt-1.5 w-full px-3 py-2.5 text-sm outline-none transition-all duration-200";

  const fieldStyle = {
    fontFamily: F.body,
    color: C.ink,
    border: `1px solid ${C.rule}`,
    borderRadius: "8px",
    minHeight: 44,
  };

  return (
    <div className="cb-shell flex min-h-screen w-full">
      {/* Brand panel */}
      <aside
        className="relative hidden w-[44%] max-w-[560px] flex-col justify-between overflow-hidden p-10 lg:flex xl:p-14"
        style={{
          background: `radial-gradient(700px 300px at 0% 0%, color-mix(in srgb, ${C.cta} 14%, transparent), transparent 70%), radial-gradient(600px 300px at 100% 100%, color-mix(in srgb, #4F8CFF 22%, transparent), transparent 70%), linear-gradient(165deg, ${C.nav} 0%, #081634 100%)`,
        }}
      >
        <div
          className="pointer-events-none absolute -left-24 top-24 h-72 w-72 rounded-full blur-[110px]"
          style={{ backgroundColor: `color-mix(in srgb, ${C.cta} 10%, transparent)` }}
        />

        <div
          className="pointer-events-none absolute -bottom-24 right-0 h-72 w-72 rounded-full blur-[120px]"
          style={{ backgroundColor: "color-mix(in srgb, #4F8CFF 16%, transparent)" }}
        />

        <div className="relative">
          <Brand />
        </div>

        <div className="relative">
          <h1
            className="max-w-md text-[38px] leading-[1.05] xl:text-[46px]"
            style={{
              fontFamily: F.editorial,
              fontWeight: 500,
              color: C.navInk,
              letterSpacing: "-0.02em",
            }}
          >
            The daybook for your <em style={{ color: C.cta, fontStyle: "italic" }}>laptop business.</em>
          </h1>

          <ul className="mt-10 space-y-6">
            {MODULES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                  style={{
                    backgroundColor: `color-mix(in srgb, ${C.cta} 12%, transparent)`,
                    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${C.cta} 25%, transparent)`,
                    color: C.cta,
                  }}
                >
                  <Icon size={18} />
                </span>

                <span>
                  <span
                    className="block text-sm"
                    style={{
                      fontFamily: F.body,
                      fontWeight: 700,
                      color: C.navInk,
                    }}
                  >
                    {title}
                  </span>

                  <span
                    className="mt-1 block max-w-sm text-[13px] leading-relaxed"
                    style={{ fontFamily: F.body, color: C.navInkSoft }}
                  >
                    {text}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p
          className="relative text-[10px] font-semibold tracking-[0.14em]"
          style={{ color: C.navInkSoft }}
        >
          SALES · RENTALS · REPAIRS · ACCOUNTS
        </p>
      </aside>

      {/* Sign-in form */}
      <main className="flex min-w-0 flex-1 items-center justify-center px-4 py-8 sm:px-8 sm:py-10">
        <div className="w-full max-w-sm">
          {/* Mobile branding */}
          <div className="mb-6 flex justify-center lg:hidden">
            <div
              className="rounded-2xl px-4 py-3"
              style={{
                background: `linear-gradient(165deg, ${C.nav} 0%, #081634 100%)`,
              }}
            >
              <Brand />
            </div>
          </div>

          <form
            onSubmit={submit}
            data-panel
            className="w-full p-5 sm:p-8"
            style={{
              backgroundColor: C.slip,
              borderRadius: "14px",
              border: `1px solid ${C.rule}`,
              boxShadow: "var(--cb-shadow-modal)",
            }}
          >
            <div className="flex items-center gap-2">
              <Lock size={14} style={{ color: C.green }} />

              <span
                className="text-[11px] uppercase"
                style={{
                  fontFamily: F.body,
                  fontWeight: 700,
                  letterSpacing: "0.18em",
                  color: C.green,
                }}
              >
                Secure sign-in
              </span>
            </div>

            <h2
              className="mt-3 text-[30px] leading-none"
              style={{
                fontFamily: F.editorial,
                fontWeight: 600,
                color: C.ink,
              }}
            >
              Sign in
            </h2>

            <p
              className="mt-1.5 text-sm leading-relaxed"
              style={{ fontFamily: F.body, color: C.inkSoft }}
            >
              Use your account credentials to access your workspace.
            </p>

            {/* Username */}
            <label
              className="mt-6 block text-xs"
              style={{
                fontFamily: F.body,
                fontWeight: 600,
                color: C.inkSoft,
              }}
            >
              Username

              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                className={fieldClass}
                style={fieldStyle}
              />
            </label>

            {/* Password with show/hide button */}
            <label
              className="mt-4 block text-xs"
              style={{
                fontFamily: F.body,
                fontWeight: 600,
                color: C.inkSoft,
              }}
            >
              Password

              <div className="relative mt-1.5">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  className="w-full py-2.5 pl-3 pr-12 text-sm outline-none transition-all duration-200"
                  style={fieldStyle}
                />

                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  title={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-1 flex w-10 items-center justify-center rounded-lg transition-all duration-200 active:scale-95"
                  style={{
                    color: showPassword ? C.ink : C.inkSoft,
                  }}
                >
                  {showPassword ? (
                    <EyeOff size={18} strokeWidth={1.9} />
                  ) : (
                    <Eye size={18} strokeWidth={1.9} />
                  )}
                </button>
              </div>
            </label>

            {/* Error message */}
            {error && (
              <p
                role="alert"
                className="mt-4 rounded-xl px-3 py-2.5 text-xs"
                style={{
                  fontFamily: F.body,
                  fontWeight: 600,
                  color: C.carbon,
                  backgroundColor: `color-mix(in srgb, ${C.carbon} 5%, transparent)`,
                  border: `1px solid color-mix(in srgb, ${C.carbon} 20%, transparent)`,
                }}
              >
                {error}
              </p>
            )}

            {/* Submit button */}
            <button
              type="submit"
              disabled={busy}
              data-variant="primary"
              className="v2x-btn mt-6 flex min-h-[46px] w-full items-center justify-center gap-2 py-3 text-sm active:scale-[0.99] disabled:cursor-wait disabled:opacity-70"
              style={{ fontFamily: F.body, fontWeight: 700 }}
            >
              <LogIn size={15} />
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
