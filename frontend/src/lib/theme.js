/*
 * Vantage2x -- enterprise suite visual identity.
 *
 * Every colour here is a CSS custom property defined in src/index.css
 * (light values on :root, dark values on :root[data-theme="dark"]), so the
 * inline styles across the app follow the active theme automatically.
 * Tints are written color-mix(in srgb, <token> N%, transparent) -- never
 * `color-mix(in srgb, ${C.x} 33%, transparent)`, which only works with literal hex values.
 *
 * `frontend/src/lib/pilotTheme.js` re-exports this file.
 */
export const APP_NAME = "Vantage2x";
export const APP_VERSION = "Enterprise Suite";
export const APP_FULL_NAME = `${APP_NAME} ${APP_VERSION}`;

const v = (name) => `var(--${name})`;

export const C = {
  ink: v("cb-ink"),
  inkSoft: v("cb-ink-soft"),
  inkFaint: v("cb-ink-faint"),
  paper: v("cb-paper"),
  slip: v("cb-surface"),        // card / panel surface
  slip2: v("cb-inset"),         // a step in from the surface
  deep: v("cb-deep"),
  rule: v("cb-rule"),
  ruleStrong: v("cb-rule-strong"),
  stamp: v("cb-accent"),        // interface accent: royal blue (light) / soft blue (dark)
  orange: v("cb-accent"),       // historic name for the same accent
  carbon: v("cb-red"),          // coral -- warnings, defects, money owed
  green: v("cb-green"),         // teal -- positive progress, paid
  amber: v("cb-amber"),         // amber -- attention
  blue: v("cb-blue"),           // ultraviolet -- secondary / analytics
  violet: v("cb-violet"),
  onAccent: v("cb-on-accent"),
  onAccentLight: v("cb-ink"),
  cta: v("cb-cta"),             // solar amber -- the one important action
  onCta: v("cb-on-cta"),

  // navigation surface (deep navy)
  nav: v("cb-nav-bg"),
  navInk: v("cb-nav-ink"),
  navInkSoft: v("cb-nav-ink-soft"),
  navLine: v("cb-nav-line"),
  navHover: v("cb-nav-hover"),
  sidebarActive: v("v-amber"),
  sidebarActiveText: v("cb-on-cta"),
  sidebarText: v("cb-nav-ink"),
  sidebarTextDim: v("cb-nav-ink-soft"),
  sidebarHover: v("cb-nav-hover"),
};

/** A see-through version of a colour token: tint(C.green, 8) */
export const tint = (color, percent) => `color-mix(in srgb, ${color} ${percent}%, transparent)`;

export const F = {
  display: "var(--cb-font-display)",
  editorial: "var(--cb-font-editorial)",
  body: "var(--cb-font-body)",
  mono: "var(--cb-font-mono)",
};

// Surface styles for the key screens -- hairline border, soft shadow.
export const heavyPanel = {
  border: `1px solid ${C.rule}`,
  backgroundColor: C.slip,
  boxShadow: "var(--cb-shadow-2)",
};

export const heavyPanelAccent = (color = C.orange) => ({
  border: `1px solid ${tint(color, 33)}`,
  backgroundColor: C.slip,
  boxShadow: "var(--cb-shadow-2)",
});

export const money = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));

export const compact = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);

/* Today's date as YYYY-MM-DD in the user's local timezone. toISOString()
   is UTC, which in India gives yesterday's date before 5:30 AM. */
export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const fmt = (d) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
