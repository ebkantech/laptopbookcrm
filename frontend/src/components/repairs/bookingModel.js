// Pure helpers for the new-ticket form: prices and the advance are typed in, never mapped from the catalogue.

export const blankLine = () => ({ description: "", quantity: 1, unit_price: "" });

export function cleanLines(lines) {
  return (lines || [])
    .filter((l) => String(l.description || "").trim() || String(l.unit_price ?? "") !== "")
    .map((l) => ({ description: String(l.description || "").trim(), quantity: Number(l.quantity) || 0, unit_price: String(l.unit_price ?? "") === "" ? NaN : Number(l.unit_price) }));
}

export function linesTotal(lines) {
  return cleanLines(lines).reduce((sum, l) => sum + (Number.isFinite(l.unit_price) ? l.quantity * l.unit_price : 0), 0);
}

// Returns an error message, or "" when the device's pricing is fine.
export function validatePricing({ lines, payment, advance, needLines }) {
  const clean = cleanLines(lines);
  if (needLines && !clean.length) return "Add at least one work or part line with its price.";
  if (clean.some((l) => !l.description || l.quantity < 1 || !Number.isFinite(l.unit_price) || l.unit_price < 0)) return "Every line needs a description, quantity and a price.";
  if (payment === "advance" && String(advance ?? "") !== "") {
    const amount = Number(advance);
    if (!Number.isFinite(amount) || amount < 0) return "Enter the advance as an amount of zero or more.";
    if (clean.length && amount > linesTotal(clean)) return "The advance can't be more than the estimate total.";
  }
  return "";
}

// Payload fragment for one device / ticket. advance_amount is always explicit so the server never assumes 25%.
export function pricingPayload({ lines, payment, advance, canPrice }) {
  const out = {};
  if (canPrice) out.estimate_lines = cleanLines(lines);
  if (payment === "advance") out.advance_amount = String(advance ?? "") === "" ? 0 : Number(advance);
  return out;
}
