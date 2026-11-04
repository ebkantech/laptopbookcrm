import test from "node:test";
import assert from "node:assert/strict";
import { canRevise, revisionLines, unitsOnInvoice } from "./invoiceRevision.js";

const canAll = () => true;
const sale = {
  id: 7, code: "INV-3600", source: "sale", status: "Payment link sent", party: 3, stock_point: 1,
  items: [{ id: 1, variant: 11, qty: 3, price: 40000 }, { id: 2, variant: 21, qty: 1, price: 1500 }, { id: 3, variant: 11, qty: 1, price: 39000 }],
};
const products = [
  { id: 100, variants: [{ id: 11 }, { id: 12 }] },
  { id: 200, variants: [{ id: 21 }] },
];

test("an awaiting-payment sale shows Revise; overdue too, both being unpaid", () => {
  assert.equal(canRevise(sale, canAll), true);
  assert.equal(canRevise({ ...sale, status: "Overdue" }, canAll), true);
});

test("paid, refunded and cancelled invoices, repairs, rentals and staff without invoices.create never show Revise", () => {
  for (const status of ["Paid", "Refunded", "Cancelled"]) assert.equal(canRevise({ ...sale, status }, canAll), false);
  for (const source of ["repair", "rental"]) assert.equal(canRevise({ ...sale, source }, canAll), false);
  assert.equal(canRevise(sale, (perm) => perm !== "invoices.create"), false);
});

test("revising starts from the invoice's own lines: product, variant, quantity and price", () => {
  assert.deepEqual(revisionLines(sale, products), [
    { productId: "100", variantId: "11", qty: 3, price: "40000" },
    { productId: "200", variantId: "21", qty: 1, price: "1500" },
    { productId: "100", variantId: "11", qty: 1, price: "39000" },
  ]);
});

test("units already on the invoice count as available only at its own shop", () => {
  assert.equal(unitsOnInvoice(sale, 11, 1), 4);
  assert.equal(unitsOnInvoice(sale, 21, 1), 1);
  assert.equal(unitsOnInvoice(sale, 12, 1), 0);
  assert.equal(unitsOnInvoice(sale, 11, 2), 0);
  assert.equal(unitsOnInvoice(null, 11, 1), 0);
});
