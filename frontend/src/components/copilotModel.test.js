import assert from "node:assert/strict";
import test from "node:test";
import { actionFields, mergeTimeline, plainReply } from "./copilotModel.js";

test("actionFields shows every value that will be sent, in words", () => {
  assert.deepEqual(actionFields({ pay_method: "UPI", staff_confirmed_upi: true, other: 5 }), [
    { key: "pay_method", label: "Payment method", value: "UPI" },
    { key: "staff_confirmed_upi", label: "UPI confirmed with customer", value: "Yes" },
    { key: "other", label: "other", value: "5" },
  ]);
  assert.deepEqual(actionFields(null), []);
});

test("mergeTimeline keeps messages and action cards in order", () => {
  const rows = mergeTimeline(
    [{ id: 1, created_at: "2026-11-05T10:00:00Z" }, { id: 2, created_at: "2026-11-05T10:02:00Z" }],
    [{ id: 9, created_at: "2026-11-05T10:01:00Z" }],
  );
  assert.deepEqual(rows.map((row) => `${row.kind}${row.item.id}`), ["message1", "action9", "message2"]);
});

test("plainReply removes formatting symbols and keeps the words", () => {
  assert.equal(plainReply("1. **Mouse** (`VC-ACC-1003`)\n* one"), "1. Mouse (VC-ACC-1003)\n- one");
  assert.equal(plainReply("2 * 3 = 6"), "2 * 3 = 6");
  assert.equal(plainReply(null), "");
});
