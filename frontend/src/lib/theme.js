/*
 * VantageCRM 26X -- Refined Modern Professional theme. A cool, quiet
 * working surface and a focused cobalt accent give the existing product
 * a clearer enterprise identity while preserving its page structure.
 *
 * The same values are exposed as CSS custom properties (--cb-*) at the
 * top of src/index.css for stylesheet rules -- keep the two in sync.
 *
 * `frontend/src/lib/pilotTheme.js` re-exports this file: it was the
 * scratch file used to design this palette against a single pilot page
 * before rolling it out here. Kept as a re-export (not deleted) so any
 * file still importing from it keeps working without a further change.
 */
export const APP_NAME = "VantageCRM";
export const APP_VERSION = "26X";
export const APP_FULL_NAME = `${APP_NAME} ${APP_VERSION}`;

export const C = {
  ink: "#172033",
  inkSoft: "#667085",
  paper: "#F4F6F9",
  slip: "#FFFFFF",         // card / panel surface -- clean white, one step up from paper
  slip2: "#F8FAFC",
  deep: "#172033",
  rule: "#E3E8F0",
  ruleStrong: "#CBD3E1",
  stamp: "#3157D5",
  carbon: "#C83C4A",
  green: "#16845B",
  amber: "#B7791F",
  blue: "#1686A8",
  orange: "#3157D5",
  onAccent: "#FFFFFF",
  onAccentLight: "#172033",

  // Sidebar-only tokens -- the sidebar is its own dark surface sitting
  // next to an otherwise light app, so it needs its own text/accent
  // scale rather than reusing ink/inkSoft (tuned for light backgrounds).
  sidebarActive: "#3157D5",
  sidebarActiveText: "#FFFFFF",
  sidebarText: "#C9D1E0",
  sidebarTextDim: "#929DB1",
  sidebarHover: "#252D3C",
};

export const F = {
  display: "'Archivo', 'Inter Tight', ui-sans-serif, system-ui, sans-serif",
  body: "'Public Sans', ui-sans-serif, system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
};

// Reusable "heavy" surface styles for the key screens -- a clean border
// plus a soft, understated shadow (this theme reads as a paper ledger,
// not a live-tracking dashboard -- no glowing neon shadows).
export const heavyPanel = {
  border: `1px solid ${C.rule}`,
  backgroundColor: C.slip,
  boxShadow: "0 1px 2px rgba(35,40,31,0.04), 0 10px 24px rgba(35,40,31,0.06)",
};

export const heavyPanelAccent = (color = C.orange) => ({
  border: `1px solid ${color}55`,
  backgroundColor: C.slip,
  boxShadow: "0 1px 2px rgba(35,40,31,0.04), 0 10px 24px rgba(35,40,31,0.06)",
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
