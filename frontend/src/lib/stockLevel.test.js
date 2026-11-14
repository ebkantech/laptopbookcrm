import { test } from "node:test";
import assert from "node:assert/strict";

import { stockTone } from "./stockLevel.js";

test("0 in stock is red", () => {
  assert.equal(stockTone(0), "red");
});

test("1 to 3 in stock is yellow", () => {
  for (const n of [1, 2, 3]) assert.equal(stockTone(n), "yellow", `quantity ${n}`);
});

test("more than 3 in stock is green", () => {
  for (const n of [4, 5, 12, 250]) assert.equal(stockTone(n), "green", `quantity ${n}`);
});

test("a missing quantity reads as 0", () => {
  for (const n of [undefined, null, "", NaN]) assert.equal(stockTone(n), "red");
});
