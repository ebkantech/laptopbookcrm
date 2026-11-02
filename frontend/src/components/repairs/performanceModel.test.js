import test from "node:test";
import assert from "node:assert/strict";
import { attentionOrder, delayLabel, formatHours, hasProblems, onTimeRate, revisionDiff } from "./performanceModel.js";

test("formatHours", () => {
  assert.equal(formatHours(null), "—");
  assert.equal(formatHours(0.25), "15 min");
  assert.equal(formatHours(5), "5 h");
  assert.equal(formatHours(5.5), "5.5 h");
  assert.equal(formatHours(50), "2d 2h");
  assert.equal(formatHours(48), "2d");
});

test("delayLabel", () => {
  assert.equal(delayLabel({ delayed: false, ready_at: "x" }), "On time");
  assert.equal(delayLabel({ delayed: false, ready_at: null }), "On track");
  assert.equal(delayLabel({ delayed: true, delay_hours: 50 }), "2d 2h late");
});

test("onTimeRate", () => {
  assert.equal(onTimeRate({ done: 0, on_time: 0 }), null);
  assert.equal(onTimeRate({ done: 4, on_time: 3 }), 75);
});

test("attention order and problems", () => {
  const rows = [
    { name: "B", overdue: 0, period: { delayed: 0 } },
    { name: "A", overdue: 2, period: { delayed: 0 } },
    { name: "C", overdue: 0, period: { delayed: 3 } },
  ];
  assert.deepEqual(attentionOrder(rows).map((r) => r.name), ["A", "C", "B"]);
  assert.equal(hasProblems(rows[0]), false);
  assert.equal(hasProblems(rows[2]), true);
});

test("revisionDiff", () => {
  assert.deepEqual(revisionDiff(1500, 2400), { diff: 900, direction: "up" });
  assert.equal(revisionDiff(2000, 1500).direction, "down");
  assert.equal(revisionDiff(1, 1).direction, "same");
});
