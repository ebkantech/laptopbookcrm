import test from "node:test";
import assert from "node:assert/strict";
import { validateAgreement, validateAssetDraft, validateInventoryPick, describeServerError, LIMITS } from "./agreementValidation.js";

const parties = [
  { id: 1, name: "Alpha", phone: "9876543210", email: "a@x.com" },
  { id: 2, name: "NoPhone", phone: "", email: "n@x.com" },
  { id: 3, name: "Nobody", phone: "", email: "" },
  { id: 4, name: "NoMail", phone: "9000000000", email: "" },
];
const ctx = { today: "2026-10-30", parties, assetLabel: (id) => `AST-${id}` };
const ok = { party: "1", start: "2026-10-30", tenure: "12", billingCycle: "3", autoInvoice: true, terms: "", lines: [{ asset_id: "1", monthly_fee: "1500" }] };
const check = (patch) => validateAgreement({ ...ok, ...patch }, ctx);

test("a complete form is valid with no errors", () => {
  const r = check({});
  assert.equal(r.valid, true);
  assert.deepEqual(r.errors.summary, []);
});

test("empty form names every missing field", () => {
  const r = check({ party: "", start: "", tenure: "", lines: [{ asset_id: "", monthly_fee: "" }] });
  assert.equal(r.valid, false);
  assert.ok(r.errors.party && r.errors.start && r.errors.tenure && r.errors.devices);
  assert.ok(r.errors.summary.length >= 4);
});

test("start date: invalid, impossible, too old, too far ahead", () => {
  assert.match(check({ start: "30/10/2026" }).errors.start, /not a valid date/);
  assert.match(check({ start: "2026-02-31" }).errors.start, /not a valid date/);
  assert.match(check({ start: "1999-01-01" }).errors.start, /more than a year in the past/);
  assert.match(check({ start: "2030-01-01" }).errors.start, /more than a year ahead/);
  assert.equal(check({ start: "2026-01-15" }).errors.start, undefined);
  assert.equal(check({ start: "2027-10-30" }).errors.start, undefined);
});

test("tenure: blank, zero, negative, decimal, text, too long, boundaries", () => {
  assert.match(check({ tenure: "" }).errors.tenure, /Enter the tenure/);
  assert.match(check({ tenure: "0" }).errors.tenure, /at least 1/);
  assert.match(check({ tenure: "-3" }).errors.tenure, /whole number/);
  assert.match(check({ tenure: "1.5" }).errors.tenure, /whole number/);
  assert.match(check({ tenure: "abc" }).errors.tenure, /whole number/);
  assert.match(check({ tenure: String(LIMITS.tenureMax + 1) }).errors.tenure, /at most 120/);
  assert.equal(check({ tenure: "1" }).errors.tenure, undefined);
  assert.equal(check({ tenure: "120" }).errors.tenure, undefined);
});

test("billing cycle must be 1, 3, 6 or 12", () => {
  for (const c of ["1", "3", "6", "12", 3]) assert.equal(check({ billingCycle: c }).errors.billingCycle, undefined);
  for (const c of ["2", "0", "", "24"]) assert.ok(check({ billingCycle: c }).errors.billingCycle);
});

test("fee: blank, zero, negative, decimal, text, too big, boundaries", () => {
  const fee = (v) => check({ lines: [{ asset_id: "1", monthly_fee: v }] }).errors.lines[0].fee;
  assert.match(fee(""), /Enter the monthly fee/);
  assert.match(fee("0"), /more than ₹0/);
  assert.match(fee("-100"), /Whole rupees/);
  assert.match(fee("1500.5"), /Whole rupees/);
  assert.match(fee("abc"), /Whole rupees/);
  assert.match(fee("1000001"), /at most/);
  assert.equal(fee("1"), undefined);
  assert.equal(fee("1000000"), undefined);
});

test("a fee typed on a row with no device is flagged, not silently dropped", () => {
  const r = check({ lines: [{ asset_id: "1", monthly_fee: "1500" }, { asset_id: "", monthly_fee: "900" }] });
  assert.equal(r.valid, false);
  assert.match(r.errors.lines[1].asset, /Choose the device/);
});

test("an untouched spare row is ignored", () => {
  const r = check({ lines: [{ asset_id: "1", monthly_fee: "1500" }, { asset_id: "", monthly_fee: "" }] });
  assert.equal(r.valid, true);
});

test("the same device twice is flagged on the second row", () => {
  const r = check({ lines: [{ asset_id: "1", monthly_fee: "1500" }, { asset_id: "1", monthly_fee: "1500" }] });
  assert.equal(r.valid, false);
  assert.equal(r.errors.lines[0].asset, undefined);
  assert.match(r.errors.lines[1].asset, /already on the agreement/);
});

test("terms: 2000 ok, 2001 too long", () => {
  assert.equal(check({ terms: "x".repeat(2000) }).errors.terms, undefined);
  assert.match(check({ terms: "x".repeat(2001) }).errors.terms, /2001\/2000/);
});

test("warnings: contact details, back-dated start, cycle longer than tenure", () => {
  assert.deepEqual(check({}).warnings.filter((w) => /phone|email/.test(w)), []);
  assert.match(check({ party: "2" }).warnings.join(" "), /no phone number.*email only/);
  assert.match(check({ party: "3" }).warnings.join(" "), /cannot reach them/);
  assert.match(check({ party: "4" }).warnings.join(" "), /WhatsApp only/);
  assert.equal(check({ party: "3", autoInvoice: false }).warnings.length, 0);
  assert.match(check({ start: "2026-06-01" }).warnings.join(" "), /one per day/);
  assert.match(check({ tenure: "3", billingCycle: "12" }).warnings.join(" "), /single invoice will cover all 3 months/);
  assert.equal(check({ tenure: "12", billingCycle: "3" }).warnings.length, 0);
});

test("server errors: network, 500, 401, 403", () => {
  assert.match(describeServerError(new Error("Failed to fetch")).message, /Couldn't reach the server/);
  assert.match(describeServerError({ status: 500, body: {}, message: "Internal Server Error" }).message, /nothing was saved/);
  assert.match(describeServerError({ status: 401, body: { detail: "x" } }).message, /session has expired/);
  assert.equal(describeServerError({ status: 403, body: { detail: "You do not have permission to perform this action." } }).message, "You do not have permission to perform this action.");
});

test("server errors name the field and never print [object Object]", () => {
  const nested = describeServerError({ status: 400, body: { lines: [{ monthly_fee: ["Ensure this value is greater than or equal to 0."] }, {}] } });
  assert.doesNotMatch(nested.message, /object Object/);
  assert.match(nested.message, /Device 1 — Monthly fee: Ensure this value/);
  const fields = describeServerError({ status: 400, body: { tenure_months: ["Ensure this value is greater than or equal to 1."], party: ["Invalid pk \"99\" - object does not exist."] } });
  assert.match(fields.message, /Tenure: Ensure/);
  assert.match(fields.message, /Customer: Invalid pk/);
  assert.equal(typeof fields.fields.tenure_months, "string");
  const plain = describeServerError({ status: 400, body: { lines: ["The same asset cannot be added twice to one rental agreement."] } });
  assert.match(plain.message, /Devices: The same asset cannot be added twice/);
  assert.match(describeServerError({ status: 400, body: { non_field_errors: ["Nope."] } }).message, /Nope\./);
  assert.match(describeServerError({ status: 400, body: { detail: "Bad.", handover: "x" } }).message, /^Bad\./);
});

test("register-device form names each missing or too-long field", () => {
  const none = validateAssetDraft({ asset_tag: "", serial_number: "", brand: "", model_name: "" });
  assert.deepEqual(Object.keys(none.errors).sort(), ["brand", "model_name", "serial_number"]);
  assert.match(none.errors.serial_number, /serial number/i);
  assert.equal(validateAssetDraft({ asset_tag: "", serial_number: "   ", brand: "Dell", model_name: "X" }).errors.serial_number !== undefined, true);
  const long = validateAssetDraft({ asset_tag: "T".repeat(49), serial_number: "S".repeat(81), brand: "B".repeat(41), model_name: "M".repeat(81) });
  assert.deepEqual(Object.keys(long.errors).sort(), ["asset_tag", "brand", "model_name", "serial_number"]);
  assert.match(long.errors.serial_number, /at most 80/);
  assert.match(long.errors.brand, /at most 40/);
  assert.equal(validateAssetDraft({ asset_tag: "T".repeat(48), serial_number: "S".repeat(80), brand: "B".repeat(40), model_name: "M".repeat(80) }).summary.length, 0);
});

test("inventory form needs an item and a serial number", () => {
  assert.deepEqual(Object.keys(validateInventoryPick({ stockId: "", serial: "", tag: "" }).errors).sort(), ["serial_number", "stock"]);
  assert.equal(validateInventoryPick({ stockId: "3", serial: "SN1", tag: "" }).summary.length, 0);
  assert.match(validateInventoryPick({ stockId: "3", serial: "S".repeat(81), tag: "" }).errors.serial_number, /at most 80/);
  assert.match(validateInventoryPick({ stockId: "3", serial: "SN1", tag: "T".repeat(49) }).errors.asset_tag, /at most 48/);
});

test("server field errors for assets name the field", () => {
  assert.match(describeServerError({ status: 400, body: { serial_number: ["Ensure this field has no more than 80 characters."] } }).message, /Serial number: Ensure/);
});
