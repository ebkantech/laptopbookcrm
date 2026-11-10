import test from "node:test";
import assert from "node:assert/strict";
import { periodRange } from "./period.js";

test("quick periods", () => {
  assert.deepEqual(periodRange("month", "2026-11-10"), { date_from: "2026-11-01", date_to: "2026-11-10" });
  assert.deepEqual(periodRange("last-month", "2026-03-05"), { date_from: "2026-02-01", date_to: "2026-02-28" });
  assert.deepEqual(periodRange("last-month", "2026-01-15"), { date_from: "2025-12-01", date_to: "2025-12-31" });
  assert.deepEqual(periodRange("year", "2026-11-10"), { date_from: "2026-01-01", date_to: "2026-11-10" });
  assert.deepEqual(periodRange("all", "2026-11-10"), { date_from: "", date_to: "" });
});
