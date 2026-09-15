/*
 * Light theme. `paper` (page background) and `deep` (sidebar) are kept
 * close in value on purpose -- the sidebar reads as a subtle panel
 * rather than a contrasting block. `slip`/`slip2` step up in
 * lightness for cards and their nested rows.
 */
export const C = {
  ink: "#161B2C",       // primary text (dark, on light surfaces)
  inkSoft: "#5B6478",   // muted / secondary text
  paper: "#F3F5F9",     // app background (lightest)
  slip: "#FFFFFF",      // card / panel surface
  slip2: "#EEF1F6",     // nested / inset surface
  deep: "#EAECF2",      // sidebar & top-bar surface -- close to `paper`, low contrast
  rule: "#DDE1E9",      // hairlines & borders
  stamp: "#2F6FE0",     // primary accent -- blue
  carbon: "#D6455A",    // danger / overdue / high risk -- red
  green: "#1E9974",     // positive / paid / healthy -- green
  amber: "#B87309",     // watch / pending -- amber
  blue: "#7C5CE0",      // tertiary accent -- violet
  orange: "#E86A1C",    // tab / active-indicator accent -- orange
  onAccent: "#FFFFFF",  // text placed on top of a solid accent colour
};

export const F = {
  display: "'Familjen Grotesk', ui-sans-serif, system-ui, sans-serif",
  body: "'Public Sans', ui-sans-serif, system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
};

export const money = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));

export const compact = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);

export const fmt = (d) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
