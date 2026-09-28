/*
 * VantageCRM 26X -- "Vantage Daybook" theme. Redesigned from the earlier
 * dark "Night Grid" look to a warm, paper-toned working surface, after a
 * reference screenshot (a housing-society management app called "Kosh"):
 * a warm cream content area, white cards with soft shadows instead of
 * neon glows, a deep forest-charcoal sidebar with a sage-green active-item
 * pill, and a single warm-orange hero accent for primary actions. Every
 * page in the app reads these same tokens, so this file is the one place
 * that reskins the whole thing -- individual pages should keep consuming
 * `C`/`F` rather than hardcoding a hex value.
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
  ink: "#23281F",          // primary text -- near-black warm charcoal, for legibility on cream/white
  inkSoft: "#83806C",      // secondary text / metadata -- muted warm taupe
  paper: "#F3EEE2",        // app background -- warm cream, never a stark white or dark navy
  slip: "#FFFFFF",         // card / panel surface -- clean white, one step up from paper
  slip2: "#F7F3EA",        // nested / inset surface -- a soft warm off-white
  deep: "#16211C",         // sidebar & top-bar surface -- deep forest-charcoal
  rule: "#E7E0CF",         // hairlines & borders -- warm sand, clean and unobtrusive
  ruleStrong: "#D8CFB8",   // heavier border for emphasis panels / headers
  stamp: "#E17A2D",        // THE hero accent -- warm orange: primary CTAs, active tab indicators
  carbon: "#C0473A",       // Overdue / Payment failed -- muted brick red
  green: "#2F6B4A",        // Available / Ready for pickup / approved -- sage green
  amber: "#C98A22",        // Out with customer / warning -- warm ochre
  blue: "#4C6FA0",         // Booked future / Reserved -- muted slate blue
  orange: "#E17A2D",       // kept as an alias of `stamp` so every existing "brand accent" usage (tab indicators, CTA fills, StatCard stripes) picks up the same warm orange rather than a second competing color
  onAccent: "#FFFFFF",     // text placed on top of a solid orange/green fill
  onAccentLight: "#23281F", // text placed on top of a light surface where onAccent (white) would be illegible

  // Sidebar-only tokens -- the sidebar is its own dark surface sitting
  // next to an otherwise light app, so it needs its own text/accent
  // scale rather than reusing ink/inkSoft (tuned for light backgrounds).
  sidebarActive: "#2F6B4A",      // active nav item's filled pill
  sidebarActiveText: "#FFFFFF",
  sidebarText: "#C9D3C7",        // default (inactive) nav label color
  sidebarTextDim: "#7C8C81",     // section headings, muted rows
  sidebarHover: "#22302A",       // hover backing for an inactive row
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

export const fmt = (d) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
