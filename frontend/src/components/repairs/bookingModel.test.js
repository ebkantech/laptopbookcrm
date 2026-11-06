import test from "node:test";
import assert from "node:assert/strict";
import { cleanLines, linesTotal, pricingPayload, validatePricing } from "./bookingModel.js";

const lines = [{ description: " Board fix ", quantity: "2", unit_price: "1500" }, { description: "", quantity: 1, unit_price: "" }];

test("cleanLines drops empty rows and coerces numbers", () => {
  assert.deepEqual(cleanLines(lines), [{ description: "Board fix", quantity: 2, unit_price: 1500 }]);
});

test("linesTotal", () => assert.equal(linesTotal(lines), 3000));

test("validatePricing", () => {
  assert.match(validatePricing({ lines: [], payment: "full", needLines: true }), /at least one/);
  assert.match(validatePricing({ lines: [{ description: "x", quantity: 1, unit_price: "" }], payment: "full" }), /price/);
  assert.match(validatePricing({ lines, payment: "advance", advance: "5000" }), /more than/);
  assert.equal(validatePricing({ lines, payment: "advance", advance: "1000" }), "");
  assert.equal(validatePricing({ lines, payment: "advance", advance: "" }), "");
  assert.match(validatePricing({ lines, payment: "advance", advance: "-5" }), /zero or more/);
});

test("pricingPayload is explicit about the advance and only prices for those who may", () => {
  assert.deepEqual(pricingPayload({ lines, payment: "advance", advance: "1000", canPrice: true }), { estimate_lines: [{ description: "Board fix", quantity: 2, unit_price: 1500 }], advance_amount: 1000 });
  assert.deepEqual(pricingPayload({ lines, payment: "advance", advance: "", canPrice: false }), { advance_amount: 0 });
  assert.deepEqual(pricingPayload({ lines, payment: "full", advance: "900", canPrice: true }), { estimate_lines: [{ description: "Board fix", quantity: 2, unit_price: 1500 }] });
});

test("our cost is sent only when typed in, and must be a valid amount", () => {
  assert.deepEqual(cleanLines([{ description: "Screen", quantity: 1, unit_price: "6000", unit_cost: "3500" }]),
    [{ description: "Screen", quantity: 1, unit_price: 6000, unit_cost: 3500 }]);
  assert.equal(validatePricing({ lines: [{ description: "Screen", quantity: 1, unit_price: "6000", unit_cost: "3500" }], payment: "full" }), "");
  assert.match(validatePricing({ lines: [{ description: "Screen", quantity: 1, unit_price: "6000", unit_cost: "-1" }], payment: "full" }), /Our cost/);
});

test("an inventory part line needs its serial number, once", () => {
  const picked = { description: "SSD 512GB", quantity: 1, unit_price: "3000", variant: 7, serial_number: "" };
  assert.match(validatePricing({ lines: [picked], payment: "full", needLines: true }), /serial number for SSD 512GB/);
  const ok = { ...picked, serial_number: "SSD-001" };
  assert.equal(validatePricing({ lines: [ok], payment: "full", needLines: true }), "");
  assert.match(validatePricing({ lines: [ok, { ...ok }], payment: "full", needLines: true }), /same serial/);
});

test("pricingPayload sends the picked parts, and nothing extra on plain lines", () => {
  const line = { description: "SSD 512GB", quantity: 1, unit_price: "3000", variant: 7, serial_number: " SSD-001 ", serials: ["SSD-001"] };
  const out = pricingPayload({ lines: [line], payment: "full", advance: "", canPrice: true });
  assert.deepEqual(out.parts, [{ variant: 7, serial_number: "SSD-001" }]);
  assert.deepEqual(out.estimate_lines, [{ description: "SSD 512GB", quantity: 1, unit_price: 3000 }]);
  assert.equal("parts" in pricingPayload({ lines, payment: "full", advance: "", canPrice: true }), false);
});

test("a serial the inventory check rejected, or one still being checked, blocks the ticket", () => {
  const line = { description: "SSD 512GB", quantity: 1, unit_price: "3000", variant: 7, serial_number: "SSD-999" };
  const bad = { ...line, serial_check: { state: "bad", message: "Serial SSD-999 was not found in stock at Store A." } };
  assert.equal(validatePricing({ lines: [bad], payment: "full", needLines: true }), "Serial SSD-999 was not found in stock at Store A.");
  assert.match(validatePricing({ lines: [{ ...line, serial_check: { state: "checking" } }], payment: "full", needLines: true }), /Still checking/);
  assert.equal(validatePricing({ lines: [{ ...line, serial_check: { state: "ok", message: "found" } }], payment: "full", needLines: true }), "");
  // a plain work line never needs a serial
  assert.equal(validatePricing({ lines: [{ description: "Motherboard repair", quantity: 1, unit_price: "900" }], payment: "full", needLines: true }), "");
});

test("a picked repair service keeps its service_id; a part line is always one unit", () => {
  const svc = { description: "SSD replacement", quantity: "3", unit_price: "3500", service_id: 4, variant: 7, serial_number: "SSD-1" };
  assert.deepEqual(cleanLines([svc]), [{ service_id: 4, description: "SSD replacement", quantity: 1, unit_price: 3500 }]);
  const labourService = { description: "Windows installation", quantity: "1", unit_price: "800", service_id: 5 };
  assert.deepEqual(cleanLines([labourService]), [{ service_id: 5, description: "Windows installation", quantity: 1, unit_price: 800 }]);
  assert.equal(validatePricing({ lines: [labourService], payment: "full", needLines: true }), "");
  assert.match(validatePricing({ lines: [{ ...svc, serial_number: "" }], payment: "full", needLines: true }), /serial number for SSD replacement/);
});
