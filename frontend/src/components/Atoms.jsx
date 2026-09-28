import { Lock, Search, TrendingDown, TrendingUp } from "lucide-react";
import { C, F } from "../lib/theme";

export function Eyebrow({ children }) {
  return (
    <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.14em", color: C.inkSoft }}>
      {children}
    </p>
  );
}

// Vantage Daybook: a status pill is a flat, light tint badge -- soft
// fill, full-strength colored text, no border or glow -- legible in a
// dense list without turning the table into a wall of solid color or
// leaving a neon halo on a white/cream surface.
export function Pill({ color, children }) {
  return (
    <span
      data-pill
      className="badge inline-flex items-center gap-1 px-2 py-0.5 text-xs"
      style={{
        display: "inline-flex", alignItems: "center", gap: 4, fontFamily: F.body, fontWeight: 700,
        color, backgroundColor: `${color}18`,
      }}
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
        {Icon && (
          <span className="flex h-7 w-7 items-center justify-center rounded-full" style={{ backgroundColor: `${C.orange}16` }}>
            <Icon size={14} style={{ color: C.orange }} />
          </span>
        )}
      </div>
      <p className="mt-2 text-2xl" style={{ fontFamily: F.display, fontWeight: 800, color: C.ink }}>{value}</p>
      {sub && (
        <p className="mt-1 flex items-center gap-1 text-xs" style={{ fontFamily: F.mono, fontWeight: 600, color: trend === "down" ? C.carbon : trend === "up" ? C.green : C.inkSoft }}>
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

// Vantage Daybook: a "patch" bar -- a horizontal white rounded strip that
// holds a row of pill-shaped tabs, active tab filled with the hero-orange
// accent. Mirrors the reference's tab row (e.g. History / Compare /
// Income / Members / Vendors / Audit pack) so any page with a tab or
// view-toggle row reads as the same rounded, modern chrome instead of an
// underlined text-tab strip.
export function TabBar({ tabs, value, onChange }) {
  return (
    <div
      className="inline-flex flex-wrap items-center gap-1 rounded-full p-1"
      style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 1px 2px rgba(35,40,31,0.04)" }}
    >
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t.id)}
            className="flex items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs"
            style={{
              fontFamily: F.body, fontWeight: 700,
              color: active ? C.onAccent : C.inkSoft,
              backgroundColor: active ? C.orange : "transparent",
            }}
          >
            {t.icon && <t.icon size={13} />}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

// Vantage Daybook: a "chip" action button -- white/cream pill with a
// hairline border, icon + label, used for every secondary action (export,
// links, filters...). `primary` swaps it to a solid orange fill for the
// one action per row that matters most, mirroring the reference's single
// solid button next to a row of white ones.
export function PillButton({ icon: Icon, children, primary = false, onClick, type = "button", disabled = false, className = "" }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs disabled:opacity-50 ${className}`}
      style={{
        fontFamily: F.body, fontWeight: 700,
        color: primary ? C.onAccent : C.ink,
        backgroundColor: primary ? C.orange : C.slip,
        border: primary ? "none" : `1px solid ${C.rule}`,
        boxShadow: primary ? "0 1px 2px rgba(35,40,31,0.08)" : "none",
      }}
    >
      {Icon && <Icon size={13} />}
      {children}
    </button>
  );
}

// Vantage Daybook: the search box is its own pill-shaped surface with a
// soft resting shadow (data-searchbox in index.css handles the shadow,
// radius, and the whole-pill focus ring) -- shared by Inventory, Parties,
// and Sales & Invoices so all three read as the same control. The inner
// input stays fully borderless/transparent; the pill carries all the
// chrome so there's never a visible double-border.
export function SearchInput({ value, onChange, placeholder, className = "", autoFocus = false }) {
  return (
    <div data-searchbox className={`flex min-w-0 flex-1 items-center gap-2 px-4 py-2.5 ${className}`}>
      <Search size={15} style={{ color: C.inkSoft, flexShrink: 0 }} />
      <input
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="w-full min-w-0 bg-transparent text-sm outline-none"
        style={{ fontFamily: F.body, color: C.ink, border: "none" }}
      />
    </div>
  );
}

export function ErrorNote({ message }) {
  if (!message) return null;
  return (
    <div className="px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.carbon, border: `1px solid ${C.carbon}44`, backgroundColor: `${C.carbon}0D` }}>
      {message}
    </div>
  );
}
