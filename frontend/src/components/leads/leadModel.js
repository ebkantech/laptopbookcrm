/* `tone` is a key of the theme palette (lib/theme C); kept as a name so this
 * file stays free of app imports and can be unit-tested with node. */
/* One vocabulary for the on-site service job states, so the board, the
 * detail panel and the timeline never call the same thing two names. */
export const LEAD_STATUS = {
  new: { label: "New", tone: "inkSoft" },
  assigned: { label: "Assigned", tone: "stamp" },
  visiting: { label: "At site", tone: "stamp" },
  diagnosed: { label: "Diagnosed", tone: "amber" },
  awaiting_approval: { label: "Awaiting approval", tone: "amber" },
  approved: { label: "Approved", tone: "green" },
  in_work: { label: "In work", tone: "green" },
  work_done: { label: "Payment due", tone: "orange" },
  closed: { label: "Closed", tone: "inkSoft" },
  rejected: { label: "Declined", tone: "carbon" },
  cancelled: { label: "Cancelled", tone: "inkSoft" },
  to_store: { label: "Taken to store", tone: "stamp" },
};
export const statusOf = (key) => LEAD_STATUS[key] || { label: key ? key.replace(/_/g, " ") : "—", tone: "inkSoft" };

export const PRIORITY = { low: "Low", normal: "Normal", urgent: "Urgent" };

/* The board's tabs: which statuses each one holds. */
export const TABS = [
  { id: "active", label: "Active", statuses: ["new", "assigned", "visiting", "diagnosed", "approved", "in_work"] },
  { id: "awaiting", label: "Awaiting approval", statuses: ["awaiting_approval"] },
  { id: "collect", label: "To collect", statuses: ["work_done"] },
  { id: "closed", label: "Closed", statuses: ["closed", "rejected", "to_store"] },
  { id: "cancelled", label: "Cancelled", statuses: ["cancelled"] },
];

export const tabOf = (status) => (TABS.find((t) => t.statuses.includes(status)) || TABS[0]).id;
export const inTab = (lead, tabId) => (TABS.find((t) => t.id === tabId)?.statuses || []).includes(lead.status);

export const LINE_KINDS = [
  { id: "labour", label: "Labour / service" },
  { id: "part", label: "Spare part" },
  { id: "product", label: "Product" },
];

export const lineAmount = (line) => (Number(line.qty) || 0) * (Number(line.price) || 0);
export const billTotal = (lines, visitCharge = 0) => lines.reduce((sum, l) => sum + lineAmount(l), 0) + (Number(visitCharge) || 0);

/* Returns an error string, or "" when the line is fine. Mirrors the server. */
export function validateLine(line) {
  if (!LINE_KINDS.some((k) => k.id === line.kind)) return "Choose what this line is for.";
  if (line.kind === "part" && !line.part) return "Pick the spare part.";
  if (line.kind === "product" && !line.variant) return "Pick the product.";
  if (line.kind === "labour" && !String(line.description || "").trim()) return "Describe the work.";
  const qty = Number(line.qty);
  if (!Number.isInteger(qty) || qty < 1 || qty > 999) return "Quantity must be a whole number from 1 to 999.";
  const price = Number(line.price);
  if (line.price === "" || line.price == null || !Number.isFinite(price) || price < 0) return "Enter the price (zero or more).";
  return "";
}

export function validateBill(lines) {
  if (!lines.length) return "Add at least one line to the bill.";
  for (let i = 0; i < lines.length; i += 1) {
    const message = validateLine(lines[i]);
    if (message) return `Line ${i + 1}: ${message}`;
  }
  return "";
}

/* Request body for POST /leads/:id/quote/ */
export function billPayload(lines, note = "") {
  return {
    note: note.trim(),
    lines: lines.map((l) => ({
      kind: l.kind,
      description: String(l.description || "").trim(),
      qty: Number(l.qty),
      price: Number(l.price),
      ...(l.kind === "part" ? { part: l.part } : {}),
      ...(l.kind === "product" ? { variant: l.variant } : {}),
    })),
  };
}

/* New / edited job form -> field errors ({} when valid). */
export function validateLeadForm(f) {
  const errors = {};
  if (!f.party) errors.party = "Choose the customer.";
  if (!f.stock_point) errors.stock_point = "Choose the store this job belongs to.";
  if (String(f.site_address || "").trim().length < 6) errors.site_address = "Enter the full site address.";
  if (String(f.issue || "").trim().length < 5) errors.issue = "Describe the problem.";
  const digits = String(f.contact_phone || "").replace(/\D/g, "");
  if (f.contact_phone && (digits.length < 8 || digits.length > 15)) errors.contact_phone = "Enter a valid phone number.";
  if (f.map_url && !/^https?:\/\/\S+$/i.test(f.map_url.trim())) errors.map_url = "Paste a full map link starting with https://";
  for (const key of ["visit_charge", "advance_amount"]) {
    const v = f[key];
    if (v !== "" && v != null && (!/^\d+$/.test(String(v)) || Number(v) > 1000000)) errors[key] = "Enter an amount in rupees.";
  }
  return errors;
}

export function leadPayload(f) {
  return {
    party: Number(f.party),
    stock_point: Number(f.stock_point),
    contact_name: (f.contact_name || "").trim(),
    contact_phone: (f.contact_phone || "").trim(),
    site_address: f.site_address.trim(),
    map_url: (f.map_url || "").trim(),
    device: (f.device || "").trim(),
    issue: f.issue.trim(),
    priority: f.priority || "normal",
    preferred_at: f.preferred_at ? new Date(f.preferred_at).toISOString() : null,
    assigned_to: f.assigned_to ? Number(f.assigned_to) : null,
    visit_charge: Number(f.visit_charge) || 0,
    advance_amount: Number(f.advance_amount) || 0,
  };
}

/* Payment form -> error string or "". Cash needs no reference. */
export function validatePayment({ pay_method, payment_reference, paid_on }, today) {
  if (!pay_method) return "Choose how it was paid.";
  if (pay_method !== "Cash" && !String(payment_reference || "").trim()) return "Enter the payment reference (UPI/UTR, cheque or card number).";
  if (String(payment_reference || "").length > 80) return "Keep the reference under 80 characters.";
  if (paid_on && today && paid_on > today) return "The payment date can't be in the future.";
  return "";
}

export const PAY_METHODS = ["Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"];

export const telLink = (phone) => `tel:${String(phone || "").replace(/[^\d+]/g, "")}`;
export const mapsLink = (lead) => lead.map_url || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(lead.site_address || "")}`;
