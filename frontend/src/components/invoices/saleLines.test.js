import test from "node:test";
import assert from "node:assert/strict";
import { blankLine, placeVariant, variantForProduct } from "./saleLines.js";
import { discountOff } from "./saleLines.js";

const product = { id: 1, variants: [{ id: 10 }, { id: 11 }] };
const line = (variantId, qty = 1) => ({ ...blankLine(), productId: "1", variantId: String(variantId), qty });

test("a new item fills the line", () => {
  const { lines, merged } = placeVariant([line(10), blankLine()], 1, { productId: "2", variantId: "20", price: "5" });
  assert.equal(merged, null);
  assert.equal(lines[1].variantId, "20");
});

test("the same item again raises the existing line's quantity and drops the new line", () => {
  const { lines, merged } = placeVariant([line(10, 2), blankLine()], 1, { productId: "1", variantId: "10", price: "5" });
  assert.equal(lines.length, 1);
  assert.equal(lines[0].qty, 3);
  assert.deepEqual(merged, { index: 0, qty: 3 });
});

test("the duplicate line's own quantity is added, and indexes shift correctly", () => {
  const start = [blankLine(), line(20), line(10, 1)];
  start[0].qty = 4;
  const { lines, merged } = placeVariant(start, 0, { productId: "1", variantId: "10" });
  assert.equal(lines.length, 2);
  assert.equal(lines[1].qty, 5);
  assert.deepEqual(merged, { index: 1, qty: 5 });
});

test("picking a product pre-selects a variant not already on the invoice", () => {
  assert.equal(variantForProduct(product, [line(10), blankLine()], 1).id, 11);
  assert.equal(variantForProduct(product, [line(10), line(11), blankLine()], 2).id, 10);
  assert.equal(variantForProduct({ variants: [] }, [], 0), null);
});

test("discountOff rounds to the nearest rupee", () => {
  assert.equal(discountOff(2000, "10"), 200);
  assert.equal(discountOff(999, "7.5"), 75);
  assert.equal(discountOff(2000, ""), 0);
});
