/*
 * VantageCRM 26X -- "Night Grid" theme. Built for a rental fleet &
 * delivery operation: live tracking, drop-off timers, real-time
 * inventory velocity. An oil-slick charcoal-navy canvas (never a dull
 * neutral grey), cards stepped up cleanly for map overlays and
 * customer profiles, and ONE hyper-vibrant electric-cyan hero accent
 * (`stamp`/`orange`, kept as the same hex so every existing consumer
 * of either token stays in sync) reserved for live tracking, the map,
 * and primary dispatch actions. The four inventory-flow statuses are
 * distinct, glowing colors rather than dulled tints -- this dashboard
 * is read in a hurry, often in the field, so status needs to
 * register at a glance: mint for ready, orange for out, coral-red for
 * overdue, lavender for booked/reserved.
 */
export const APP_NAME = "VantageCRM";
export const APP_VERSION = "26X";
export const APP_FULL_NAME = `${APP_NAME} ${APP_VERSION}`;

export const C = {
  ink: "#F1F4FA",        // primary text -- crisp light silver-white, for legibility under field conditions
  inkSoft: "#7C8CA6",    // secondary text / metadata -- muted smoky steel-blue
  paper: "#0B0F1A",      // app background -- deep oil-slick charcoal-navy, never a dull neutral grey
  slip: "#141A29",       // card / panel surface -- one clean step up from paper
  slip2: "#1B2436",      // nested / inset surface -- a further step up again
  deep: "#0A0E1C",       // sidebar & top-bar surface -- its own quiet, slightly richer dark
  rule: "#232D40",       // hairlines & borders -- smoky steel-blue, clean and unobtrusive
  ruleStrong: "#324058", // heavier border for emphasis panels / headers
  stamp: "#00E5FF",      // THE hero accent -- hyper-vibrant electric cyan: live tracking, the map, primary dispatch buttons
  carbon: "#FF3B5C",     // Overdue / Payment failed -- sharp neon coral-red
  green: "#00FFA3",      // Available / Ready for pickup -- vivid glowing mint
  amber: "#FF7A1A",      // Out with customer -- sleek electric orange
  blue: "#B39DFF",       // Booked future / Reserved -- soft icy lavender
  orange: "#00E5FF",     // kept as an alias of `stamp` so every existing "brand accent" usage (tab indicators, CTA fills, StatCard stripes) picks up the same electric cyan rather than a second competing color
  onAccent: "#04141A",   // text placed on top of a solid cyan/mint fill
  onAccentLight: "#F1F4FA", // text placed on top of a solid dark surface
};

export const F = {
  display: "'Archivo', 'Inter Tight', ui-sans-serif, system-ui, sans-serif",
  body: "'Public Sans', ui-sans-serif, system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
};

// Reusable "heavy" surface styles for the key screens -- a clean
// border plus a soft, glowing shadow (never a hard offset block --
// this theme reads as live-tracking-software, not a printed sticker).
export const heavyPanel = {
  border: `1px solid ${C.ruleStrong}`,
  backgroundColor: C.slip,
  boxShadow: "0 8px 28px rgba(0,0,0,0.55)",
};

export const heavyPanelAccent = (color = C.orange) => ({
  border: `1px solid ${color}`,
  backgroundColor: C.slip,
  boxShadow: `0 0 0 1px ${color}33, 0 8px 28px rgba(0,0,0,0.55)`,
});

export const money = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));

export const compact = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);

export const fmt = (d) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
