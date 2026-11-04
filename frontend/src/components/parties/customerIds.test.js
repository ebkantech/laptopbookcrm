import test from "node:test";
import assert from "node:assert/strict";
import { idProblem, verhoeffOk } from "./customerIds.js";

test("Aadhaar check digit", () => {
  assert.equal(verhoeffOk("234123412346"), true);
  assert.equal(verhoeffOk("234123412345"), false);
  assert.equal(idProblem("aadhaar", "2341 2341 2346"), "");
  assert.match(idProblem("aadhaar", "123412341234"), /doesn't start with 0 or 1/);
});

test("PAN and other formats", () => {
  assert.equal(idProblem("pan", "abcpe1234f"), "");
  assert.match(idProblem("pan", "ABCXE1234F"), /holder type/);
  assert.equal(idProblem("passport", "K1234567"), "");
  assert.notEqual(idProblem("voter_id", "AB1234567"), "");
});
