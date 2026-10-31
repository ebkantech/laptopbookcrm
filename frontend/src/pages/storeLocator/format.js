/* Plain helpers for the Store & Channel Management views (no components). */

// Fallback for the business's low-stock line until the inventory payload
// reports it (catalog.views.LOW_STOCK_THRESHOLD, the same 4 units the
// existing /products/low-stock/ rule uses). Never a separate rule.
export const LOW_STOCK_AT = 4;
export const PENDING_MESSAGE = "Your Store Location has not been assigned yet. Please contact your administrator.";

const nf = new Intl.NumberFormat("en-IN");
export const num = (n) => nf.format(n || 0);
export const plural = (n, word, many = `${word}s`) => `${num(n)} ${n === 1 ? word : many}`;

export const isShop = (sp) => sp.kind === "shop";
export const kindLabel = (sp) => (isShop(sp) ? "Physical shop" : "Online channel");
export const firstLine = (address) => (address || "").split(/\n/)[0].trim().replace(/,$/, "");
export const oneLine = (address) => (address || "").replace(/,?\s*\n\s*/g, ", ").trim();
export const personName = (u) => `${u.first_name || ""} ${u.last_name || ""}`.trim() || u.username;
export const initials = (name) => name.split(/\s+/).filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

// Exact coordinates aren't stored anywhere, so the most honest map we can
// offer is a search for the saved address text -- no key, no geocoding.
export const mapSearchUrl = (address) =>
  `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address.replace(/\s+/g, " ").trim())}`;

/* A stock record's state. `null` quantity means there is no record at all --
   never treated as zero. */
export function stockState(quantity, threshold = LOW_STOCK_AT) {
  if (quantity === null || quantity === undefined) return "none";
  if (quantity === 0) return "out";
  if (quantity <= threshold) return "low";
  return "in";
}
export const STATE_TONE = { in: "green", low: "amber", out: "red", none: "grey" };
export const STATE_LABEL = { in: "In stock", low: "Low stock", out: "Out of stock", none: "No stock record" };
