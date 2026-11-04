import test from "node:test";
import assert from "node:assert/strict";
import { fromSheet, toSheet } from "./costSheet.js";

const review = {
  variants: [{ code: "VC-SKU-0002", product: "Dell Latitude, 5440", spec: "i7", colour: "Black", sell_price: 70000 }],
  parts: [{ code: "kb-fan", name: "CPU fan" }],
};

test("toSheet quotes commas and lists products and parts", () => {
  assert.equal(toSheet(review), 'code,item,details,selling_price,cost\r\nVC-SKU-0002,"Dell Latitude, 5440",i7 / Black,70000,\r\nkb-fan,CPU fan,spare part,,\r\n');
});

test("the downloaded sheet reads back once costs are filled in", () => {
  const filled = toSheet(review).replace("70000,\r\n", '70000,"₹ 61,000"\r\n');
  assert.deepEqual(fromSheet(filled), { rows: [{ code: "VC-SKU-0002", cost: 61000 }], skipped: 1, problems: [] });
});

test("two plain columns, tabs, and bad values", () => {
  assert.deepEqual(fromSheet("VC-SKU-0001\t40000\nkb-fan\t800\n").rows, [{ code: "VC-SKU-0001", cost: 40000 }, { code: "kb-fan", cost: 800 }]);
  const bad = fromSheet("code,cost\nVC-1,abc\n,500\nVC-2,0\n");
  assert.equal(bad.rows.length, 0);
  assert.equal(bad.problems.length, 3);
  assert.deepEqual(fromSheet("").problems, ["The sheet is empty."]);
});
