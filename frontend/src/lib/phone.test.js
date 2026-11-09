import assert from "node:assert/strict";
import test from "node:test";
import { phoneError } from "./phone.js";

test("Indian mobiles in any usual shape are fine", () => {
  for (const ok of ["9876543210", "98765 43210", "+91 98765 43210", "919876543210", "09876543210", "+971 50 123 4567"]) assert.equal(phoneError(ok), "", ok);
});

test("the 00 number, short, long, dummy and lettered numbers are refused", () => {
  for (const bad of ["0050193876", "12345", "98765432101234", "5876543210", "9999999999", "98765abc10", ""]) assert.notEqual(phoneError(bad), "", bad);
  assert.match(phoneError("0050193876"), /00/);
});
