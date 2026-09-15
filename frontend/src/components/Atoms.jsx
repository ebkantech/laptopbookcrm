import { Lock, TrendingDown, TrendingUp } from "lucide-react";
import { C, F } from "../lib/theme";

export function Eyebrow({ children }) {
  return (
    <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>
      {children}
    </p>
  );
}

export function Pill({ color, children }) {
  return (
    <span
      data-pill
      className="badge inline-flex items-center gap-1 px-2 py-0.5 text-xs"
      style={{ display: "inline-flex", alignItems: "center", gap: 4, fontFamily: F.body, fontWeight: 600, color, backgroundColor: `${color}1F`, border: `1px solid ${color}55` }}
    >
      {children}
    </span>
  );
}

export function StatCard({ label, value, sub, trend, icon: Icon }) {
  return (
    <div data-panel className="flex-1 min-w-[160px] px-4 py-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
      <div className="flex items-center justify-between">
        <Eyebrow>{label}</Eyebrow>
        {Icon && <Icon size={14} style={{ color: C.inkSoft }} />}
      </div>
      <p className="mt-2 text-2xl" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{value}</p>
      {sub && (
        <p className="mt-1 flex items-center gap-1 text-xs" style={{ fontFamily: F.mono, color: trend === "down" ? C.carbon : trend === "up" ? C.green : C.inkSoft }}>
          {trend === "up" && <TrendingUp size={12} />}
          {trend === "down" && <TrendingDown size={12} />}
          {sub}
        </p>
      )}
    </div>
  );
}

export function Locked({ label }) {
  return (
    <div className="flex items-center gap-2 px-4 py-6" style={{ fontFamily: F.body, color: C.inkSoft }}>
      <Lock size={14} /> <span className="text-sm">{label}</span>
    </div>
  );
}

export function Spinner({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-2 px-4 py-10 justify-center" style={{ fontFamily: F.body, color: C.inkSoft }}>
      <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorNote({ message }) {
  if (!message) return null;
  return (
    <div className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.carbon, border: `1px solid ${C.carbon}`, backgroundColor: `${C.carbon}14` }}>
      {message}
    </div>
  );
}
