// The checklist rows on a rental card. The rules themselves live on the server
// (rentals.onboarding); these only put its answers into words.

export function invoiceStep(invoice, title) {
  if (!invoice) return { done: false, title, detail: "Invoice cancelled" };
  const amount = `₹${Number(invoice.total).toLocaleString("en-IN")}`;
  return { done: invoice.status === "Paid", title, detail: `${invoice.code} · ${amount} · ${invoice.status}` };
}

export function kycStep(state) {
  const detail = (value) => {
    if (value === "verified") return "Verified";
    return value === "recorded" ? "Recorded. Check the original, then press Verify" : "Not recorded yet";
  };
  const row = (title, value) => ({ done: value === "verified", title, detail: detail(value) });
  return [...(state.needs_aadhaar ? [row("Aadhaar", state.aadhaar)] : []), row("PAN", state.pan)];
}

/* The customer's KYC, from the ID records, for the new-agreement form: the
 * server makes the same check (rentals.onboarding.require_kyc). */
export function kycVerified(documents, classification) {
  const verified = (type) => (documents || []).some((d) => d.id_type === type && d.status === "verified");
  return verified("pan") && (classification !== "individual" || verified("aadhaar"));
}
