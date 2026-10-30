import test from "node:test";
import assert from "node:assert/strict";
import { describeRow, groupByClient, grandTotals } from "./ledgerModel.js";

const fmt = (d) => `<${d}>`;
const inv = (o) => ({ kind: "invoice", id: 1, code: "INV-1", party: 1, client_name: "Alpha", phone: "1", agreement_code: "RNT-1", period_start: "2026-01-01", total: 1000, due_date: "2026-01-01", status: "Payment link sent", paid_on: null, days_late: null, days_overdue: 0, due_in_days: 0, ...o });
const sched = (o) => ({ kind: "scheduled", id: "s1", party: 1, client_name: "Alpha", phone: "1", agreement_code: "RNT-1", period_start: "2026-04-01", total: 3000, due_date: "2026-04-01", status: "Scheduled", send_on: "2026-03-29", days_late: null, days_overdue: null, due_in_days: 5, ...o });

test("paid on time, paid late, overdue, due soon, due today, cancelled, scheduled", () => {
  assert.deepEqual(describeRow(inv({ status: "Paid", paid_on: "2026-01-01", days_late: 0 }), fmt), { label: "Paid <2026-01-01>", tone: "paid", detail: "on time", due: "Due <2026-01-01>" });
  const late = describeRow(inv({ status: "Paid", paid_on: "2026-01-05", days_late: 4 }), fmt);
  assert.equal(late.tone, "late"); assert.equal(late.detail, "4 days after the due date");
  assert.equal(describeRow(inv({ status: "Paid", paid_on: "2026-01-02", days_late: 1 }), fmt).detail, "1 day after the due date");
  const over = describeRow(inv({ status: "Overdue", days_overdue: 12 }), fmt);
  assert.equal(over.tone, "overdue"); assert.equal(over.detail, "12 days past the due date");
  assert.equal(describeRow(inv({ days_overdue: 3 }), fmt).tone, "overdue");   // status not yet flipped but past due
  assert.equal(describeRow(inv({ due_in_days: 5 }), fmt).label, "Due in 5 days");
  assert.equal(describeRow(inv({ due_in_days: 1 }), fmt).label, "Due in 1 day");
  assert.equal(describeRow(inv({ due_in_days: 0 }), fmt).label, "Due today");
  assert.equal(describeRow(inv({ status: "Cancelled" }), fmt).tone, "muted");
  const s = describeRow(sched({}), fmt, "2026-01-01");
  assert.deepEqual([s.label, s.tone, s.detail], ["Scheduled", "scheduled", "Invoice goes to the client on <2026-03-29>"]);
  assert.match(describeRow(sched({ send_on: null }), fmt).detail, /Auto-send is off/);
  assert.equal(describeRow(sched({ send_on: "2026-03-29" }), fmt, "2026-03-29").detail, "Invoice goes to the client on <2026-03-29>");
  assert.equal(describeRow(sched({ send_on: "2026-03-29" }), fmt, "2026-03-30").detail, "Goes to the client with the next daily run");
});

test("per-client history and totals", () => {
  const rows = [
    inv({ id: 1, code: "INV-1", period_start: "2026-01-01", total: 3000, status: "Paid", paid_on: "2026-01-01", days_late: 0 }),
    inv({ id: 2, code: "INV-2", period_start: "2026-04-01", total: 3000, status: "Paid", paid_on: "2026-04-06", days_late: 5 }),
    inv({ id: 3, code: "INV-3", period_start: "2026-07-01", total: 3000, status: "Overdue", days_overdue: 20 }),
    inv({ id: 4, code: "INV-4", period_start: "2026-10-01", total: 3000, due_in_days: 2 }),
    inv({ id: 5, code: "INV-5", period_start: "2026-02-01", total: 999, status: "Cancelled" }),
    sched({}),
  ];
  const [g] = groupByClient(rows);
  assert.deepEqual(g.totals, { invoiced: 12000, paid: 6000, outstanding: 6000, overdueAmount: 3000, overdueCount: 1, latePayments: 1, invoices: 4, scheduled: 1 });
  assert.equal(g.rows[0].kind, "scheduled");                                  // upcoming first
  assert.deepEqual(g.rows.slice(1).map((r) => r.code), ["INV-4", "INV-3", "INV-2", "INV-5", "INV-1"]); // newest period first
  assert.deepEqual(g.agreements, ["RNT-1"]);
});

test("clients with overdue money come first; grand totals add up", () => {
  const rows = [
    inv({ party: 1, client_name: "Alpha", total: 1000, status: "Paid", paid_on: "2026-01-01", days_late: 0 }),
    inv({ id: 9, party: 2, client_name: "Zed", total: 500, status: "Overdue", days_overdue: 3 }),
    inv({ id: 8, party: 3, client_name: "Beta", total: 700, due_in_days: 4 }),
  ];
  const groups = groupByClient(rows);
  assert.deepEqual(groups.map((g) => g.name), ["Zed", "Alpha", "Beta"]);
  assert.deepEqual(grandTotals(groups), { invoiced: 2200, paid: 1000, outstanding: 1200, overdueAmount: 500, overdueCount: 1, invoices: 3 });
});

test("refunded invoices are listed but not counted as billed", () => {
  const [g] = groupByClient([inv({ status: "Refunded", total: 800 })]);
  assert.equal(g.totals.invoiced, 0); assert.equal(g.totals.invoices, 1);
});

test("empty ledger", () => { assert.deepEqual(groupByClient([]), []); assert.equal(grandTotals([]).invoiced, 0); });
