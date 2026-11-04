import test from "node:test";
import assert from "node:assert/strict";
import { flipOrder, orderRows } from "./order.js";

test("flipOrder toggles", () => {
  assert.equal(flipOrder("asc"), "desc");
  assert.equal(flipOrder("desc"), "asc");
});

test("orderRows keeps the natural order and reverses the other way without mutating", () => {
  const rows = [1, 2, 3];
  assert.deepEqual(orderRows(rows, "asc"), [1, 2, 3]);
  assert.deepEqual(orderRows(rows, "desc"), [3, 2, 1]);
  assert.deepEqual(rows, [1, 2, 3]);
  assert.deepEqual(orderRows(rows, "asc", "desc"), [3, 2, 1]); // natural order is newest-first
  assert.deepEqual(orderRows(rows, "desc", "desc"), [1, 2, 3]);
});
