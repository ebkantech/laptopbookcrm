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
