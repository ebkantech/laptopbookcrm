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

import { C, F, APP_NAME } from "../lib/theme";
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

function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div
        className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl"
        style={{
          background: `linear-gradient(145deg, ${C.orange}, #B96716)`,
          boxShadow: `0 6px 22px ${C.orange}40`,
        }}
      >
        <span
          className="text-xl font-black"
          style={{ color: "#171A21", fontFamily: F.display }}
        >
          V
        </span>

        <span
          className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full"
          style={{ backgroundColor: "#FFF3D8" }}
        />
      </div>

      <div>
        <p
          className="text-[17px] font-extrabold tracking-wide"
          style={{ fontFamily: F.display, color: "#F9FAFB" }}
        >
          {APP_NAME}
        </p>

        <p
          className="text-[9px] font-bold uppercase tracking-[0.2em]"
          style={{ color: "#9298A5" }}
        >
          Business control
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
    "mt-1.5 w-full bg-white px-3 py-2.5 text-sm outline-none transition-all duration-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-400/15";

  const fieldStyle = {
    fontFamily: F.body,
    color: C.ink,
    border: `1px solid ${C.rule}`,
    borderRadius: "10px",
  };

  return (
    <div className="cb-shell flex min-h-screen w-full">
      {/* Brand panel */}
      <aside
        className="relative hidden w-[44%] max-w-[560px] flex-col justify-between overflow-hidden p-10 lg:flex xl:p-14"
        style={{
          background: "linear-gradient(160deg, #1B1F27 0%, #111318 100%)",
        }}
      >
        <div
          className="pointer-events-none absolute -left-24 top-24 h-72 w-72 rounded-full blur-[110px]"
          style={{ backgroundColor: `${C.orange}2A` }}
        />

        <div
          className="pointer-events-none absolute -bottom-24 right-0 h-72 w-72 rounded-full blur-[120px]"
          style={{ backgroundColor: `${C.green}30` }}
        />

        <div className="relative">
          <BrandMark />
        </div>

        <div className="relative">
          <h1
            className="max-w-md text-[34px] leading-[1.1] tracking-tight xl:text-[40px]"
            style={{
              fontFamily: F.display,
              fontWeight: 800,
              color: "#F9FAFB",
            }}
          >
            The daybook for your laptop business.
          </h1>

          <ul className="mt-10 space-y-6">
            {MODULES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
                  style={{
                    backgroundColor: `${C.orange}1F`,
                    color: C.orange,
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
                      color: "#F3F4F6",
                    }}
                  >
                    {title}
                  </span>

                  <span
                    className="mt-1 block max-w-sm text-[13px] leading-relaxed"
                    style={{ fontFamily: F.body, color: "#9AA1AE" }}
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
          style={{ color: "#6B7280" }}
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
                background:
                  "linear-gradient(160deg, #1B1F27 0%, #111318 100%)",
              }}
            >
              <BrandMark />
            </div>
          </div>

          <form
            onSubmit={submit}
            data-panel
            className="w-full p-5 sm:p-8"
            style={{
              backgroundColor: C.slip,
              borderRadius: "18px",
              border: `1px solid ${C.rule}`,
              boxShadow: "0 16px 50px rgba(20, 24, 32, 0.07)",
            }}
          >
            <div className="flex items-center gap-2">
              <Lock size={14} style={{ color: C.stamp }} />

              <span
                className="text-[11px] uppercase"
                style={{
                  fontFamily: F.body,
                  fontWeight: 700,
                  letterSpacing: "0.18em",
                  color: C.orange,
                }}
              >
                CRMBook
              </span>
            </div>

            <h2
              className="mt-3 text-2xl tracking-tight"
              style={{
                fontFamily: F.display,
                fontWeight: 800,
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
                  className="w-full bg-white py-2.5 pl-3 pr-12 text-sm outline-none transition-all duration-200 focus:ring-2 focus:ring-orange-400/15"
                  style={fieldStyle}
                />

                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  title={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-1 flex w-10 items-center justify-center rounded-lg transition-all duration-200 hover:bg-orange-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 active:scale-95"
                  style={{
                    color: showPassword ? C.orange : "#7B8492",
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
                  backgroundColor: `${C.carbon}0D`,
                  border: `1px solid ${C.carbon}33`,
                }}
              >
                {error}
              </p>
            )}

            {/* Submit button */}
            <button
              type="submit"
              disabled={busy}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm transition-all duration-200 hover:brightness-105 active:scale-[0.99] disabled:cursor-wait disabled:opacity-70"
              style={{
                backgroundColor: C.stamp,
                color: C.onAccent,
                fontFamily: F.body,
                fontWeight: 700,
                boxShadow: `0 6px 16px -6px ${C.stamp}99`,
              }}
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
