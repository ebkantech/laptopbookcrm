// Pure helpers for the new-ticket form: prices and the advance are typed in, never mapped from the catalogue.

export const blankLine = () => ({ description: "", quantity: 1, unit_price: "" });

// "Our cost" (unit_cost) is what the parts on a line cost the shop -- staff-only, for the profit report.
// Sent only when typed in; a line without it counts as labour.
export function cleanLines(lines) {
  return (lines || [])
    .filter((l) => String(l.description || "").trim() || String(l.unit_price ?? "") !== "")
    .map((l) => ({
      ...(l.service_id ? { service_id: l.service_id } : {}),
      description: String(l.description || "").trim(),
      quantity: l.variant ? 1 : Number(l.quantity) || 0,
      unit_price: String(l.unit_price ?? "") === "" ? NaN : Number(l.unit_price),
      ...(String(l.unit_cost ?? "") === "" ? {} : { unit_cost: Number(l.unit_cost) }),
    }));
}

// For panels that keep a service_id: the optional cost as the API expects it.
export const costField = (line) => (String(line.unit_cost ?? "") === "" ? {} : { unit_cost: Number(line.unit_cost) });
export const badCost = (line) => String(line.unit_cost ?? "") !== "" && !(Number(line.unit_cost) >= 0);

export function linesTotal(lines) {
  return cleanLines(lines).reduce((sum, l) => sum + (Number.isFinite(l.unit_price) ? l.quantity * l.unit_price : 0), 0);
}

// Inventory parts picked on the lines: { variant, serial_number } for each linked line.
export const partsOf = (lines) => (lines || []).filter((l) => l.variant).map((l) => ({ variant: l.variant, serial_number: String(l.serial_number || "").trim() }));

// Returns an error message, or "" when the device's pricing is fine.
export function validatePricing({ lines, payment, advance, needLines }) {
  const picked = (lines || []).filter((l) => l.variant);
  const missing = picked.find((l) => !String(l.serial_number || "").trim());
  if (missing) return `Enter the serial number for ${missing.description || "the selected part"}.`;
  const bad = picked.find((l) => l.serial_check?.state === "bad");
  if (bad) return bad.serial_check.message;
  if (picked.some((l) => l.serial_check?.state === "checking")) return "Still checking a serial number -- try again in a moment.";
  const serials = picked.map((l) => String(l.serial_number).trim().toUpperCase());
  if (new Set(serials).size !== serials.length) return "The same serial number is picked on more than one line.";
  const clean = cleanLines(lines);
  if (needLines && !clean.length) return "Add at least one work or part line with its price.";
  if (clean.some((l) => !l.description || l.quantity < 1 || !Number.isFinite(l.unit_price) || l.unit_price < 0)) return "Every line needs a description, quantity and a price.";
  if (clean.some((l) => "unit_cost" in l && !(l.unit_cost >= 0))) return "Our cost must be an amount of zero or more (or left blank).";
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
  const parts = partsOf(lines);
  if (canPrice && parts.length) out.parts = parts;
  if (payment === "advance") out.advance_amount = String(advance ?? "") === "" ? 0 : Number(advance);
  return out;
}
