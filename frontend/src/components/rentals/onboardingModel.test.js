import assert from "node:assert/strict";
import test from "node:test";
import { invoiceStep, kycStep, kycVerified } from "./onboardingModel.js";

test("invoiceStep reads the invoice's state", () => {
  assert.equal(invoiceStep({ code: "INV-1", total: 2000, status: "Paid" }, "Deposit").done, true);
  assert.equal(invoiceStep({ code: "INV-1", total: 2000, status: "Overdue" }, "Deposit").done, false);
  assert.equal(invoiceStep(null, "Deposit").detail, "Invoice cancelled");
});

test("kycStep asks a business for PAN only", () => {
  assert.deepEqual(kycStep({ needs_aadhaar: false, pan: "verified" }).map((r) => r.title), ["PAN"]);
  const rows = kycStep({ needs_aadhaar: true, aadhaar: "missing", pan: "recorded" });
  assert.deepEqual(rows.map((r) => r.title), ["Aadhaar", "PAN"]);
  assert.equal(rows[0].detail, "Not recorded yet");
  assert.equal(rows[1].done, false);
  assert.match(rows[1].detail, /Verify/);
});

test("kycVerified needs both IDs for an individual and PAN for a business", () => {
  const pan = { id_type: "pan", status: "verified" };
  const aadhaar = { id_type: "aadhaar", status: "verified" };
  assert.equal(kycVerified([pan], "business"), true);
  assert.equal(kycVerified([pan], "individual"), false);
  assert.equal(kycVerified([pan, aadhaar], "individual"), true);
  assert.equal(kycVerified([{ id_type: "pan", status: "format_ok" }], "business"), false);
});
