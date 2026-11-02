import test from "node:test";
import assert from "node:assert/strict";
import { billPayload, billTotal, inTab, leadPayload, tabOf, validateBill, validateLeadForm, validateLine, validatePayment } from "./leadModel.js";

const ok = { kind: "labour", description: "Fix jack", qty: 1, price: 500 };

test("a good line passes and a bad one explains why", () => {
  assert.equal(validateLine(ok), "");
  assert.match(validateLine({ ...ok, description: " " }), /Describe/);
  assert.match(validateLine({ ...ok, qty: 0 }), /Quantity/);
  assert.match(validateLine({ ...ok, qty: 1.5 }), /Quantity/);
  assert.match(validateLine({ ...ok, price: "" }), /price/);
  assert.match(validateLine({ ...ok, price: -1 }), /price/);
  assert.match(validateLine({ kind: "part", qty: 1, price: 5 }), /spare part/);
  assert.match(validateLine({ kind: "product", qty: 1, price: 5 }), /product/);
  assert.match(validateLine({ ...ok, kind: "wat" }), /Choose/);
});

test("bill needs lines and names the offending one", () => {
  assert.match(validateBill([]), /at least one/);
  assert.match(validateBill([ok, { ...ok, qty: 0 }]), /^Line 2:/);
  assert.equal(validateBill([ok]), "");
});

test("totals include the visit charge", () => {
  assert.equal(billTotal([ok, { ...ok, qty: 2, price: 100 }], 300), 1000);
  assert.equal(billTotal([], 0), 0);
});

test("payload carries only the right reference per kind", () => {
  const body = billPayload([ok, { kind: "part", part: 4, qty: "2", price: "450", description: "" }, { kind: "product", variant: 9, qty: 1, price: 2500 }], " note ");
  assert.equal(body.note, "note");
  assert.deepEqual(body.lines[0], { kind: "labour", description: "Fix jack", qty: 1, price: 500 });
  assert.equal(body.lines[1].part, 4);
  assert.equal(body.lines[1].qty, 2);
  assert.equal(body.lines[1].variant, undefined);
  assert.equal(body.lines[2].variant, 9);
});

test("job form validation", () => {
  assert.equal(Object.keys(validateLeadForm({})).length >= 4, true);
  const good = { party: 1, stock_point: 1, site_address: "12 MG Road", issue: "No power", visit_charge: "300" };
  assert.deepEqual(validateLeadForm(good), {});
  assert.ok(validateLeadForm({ ...good, contact_phone: "12" }).contact_phone);
  assert.ok(validateLeadForm({ ...good, map_url: "maps" }).map_url);
  assert.ok(validateLeadForm({ ...good, visit_charge: "-5" }).visit_charge);
  assert.ok(validateLeadForm({ ...good, advance_amount: "1.5" }).advance_amount);
  assert.deepEqual(validateLeadForm({ ...good, map_url: "https://maps.app.goo.gl/x", contact_phone: "+91 98765 43210" }), {});
});

test("lead payload normalises numbers and empties", () => {
  const p = leadPayload({ party: "3", stock_point: "2", site_address: " 12 MG Road ", issue: " dead ", visit_charge: "300", assigned_to: "" });
  assert.equal(p.party, 3);
  assert.equal(p.site_address, "12 MG Road");
  assert.equal(p.assigned_to, null);
  assert.equal(p.visit_charge, 300);
  assert.equal(p.preferred_at, null);
});

test("payment: reference needed except for cash, no future dates", () => {
  assert.equal(validatePayment({ pay_method: "Cash" }, "2026-10-31"), "");
  assert.match(validatePayment({ pay_method: "UPI", payment_reference: " " }, "2026-10-31"), /reference/);
  assert.equal(validatePayment({ pay_method: "UPI", payment_reference: "UTR1" }, "2026-10-31"), "");
  assert.match(validatePayment({ pay_method: "Cash", paid_on: "2026-11-05" }, "2026-10-31"), /future/);
  assert.match(validatePayment({ pay_method: "" }), /Choose/);
});

test("tabs hold the right statuses", () => {
  assert.equal(tabOf("in_work"), "active");
  assert.equal(tabOf("awaiting_approval"), "awaiting");
  assert.equal(tabOf("work_done"), "collect");
  assert.equal(tabOf("rejected"), "closed");
  assert.equal(tabOf("to_store"), "closed");
  assert.equal(tabOf("cancelled"), "cancelled");
  assert.equal(inTab({ status: "closed" }, "closed"), true);
  assert.equal(inTab({ status: "closed" }, "active"), false);
});
