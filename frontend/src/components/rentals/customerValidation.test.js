import test from "node:test";
import assert from "node:assert/strict";
import { customerPayload, findSamePhone, validateCustomer } from "./customerValidation.js";

const good = { name: "Asha Rao", phone: "98765 43210", email: "asha@example.com", city: "Pune", gstin: "" };

test("a complete customer has no errors", () => assert.deepEqual(validateCustomer(good), {}));

test("every required field is reported when empty", () => {
  const e = validateCustomer({ name: "  ", phone: "", email: "", city: "", gstin: "" });
  assert.deepEqual(Object.keys(e).sort(), ["city", "email", "name", "phone"]);
});

test("phone needs 10 to 15 digits, formatting is allowed", () => {
  assert.match(validateCustomer({ ...good, phone: "12345" }).phone, /10 to 15 digits/);
  assert.match(validateCustomer({ ...good, phone: "1".repeat(16) }).phone, /10 to 15 digits/);
  assert.equal(validateCustomer({ ...good, phone: "+91 98765-43210" }).phone, undefined);
  assert.match(validateCustomer({ ...good, phone: "abc" }).phone, /10 to 15 digits/);
});

test("email format", () => {
  for (const bad of ["asha", "asha@", "asha@x", "a b@x.com"]) assert.match(validateCustomer({ ...good, email: bad }).email, /valid email/, bad);
  assert.equal(validateCustomer({ ...good, email: "a.b+c@mail.example.co.in" }).email, undefined);
});

test("length limits", () => {
  assert.match(validateCustomer({ ...good, name: "x".repeat(121) }).name, /at most 120/);
  assert.match(validateCustomer({ ...good, city: "x".repeat(61) }).city, /at most 60/);
});

test("GSTIN is optional but must look right when given", () => {
  assert.equal(validateCustomer({ ...good, gstin: "29ABCDE1234F1Z5" }).gstin, undefined);
  assert.equal(validateCustomer({ ...good, gstin: "29abcde1234f1z5" }).gstin, undefined);
  assert.match(validateCustomer({ ...good, gstin: "12345" }).gstin, /15 characters/);
});

test("same mobile number finds the existing customer", () => {
  const parties = [{ id: 1, name: "Old", phone: "+91 98765 43210" }, { id: 2, name: "Other", phone: "9000000000" }];
  assert.equal(findSamePhone(parties, "9876543210").id, 1);
  assert.equal(findSamePhone(parties, "98765"), null);
  assert.equal(findSamePhone(parties, "9111111111"), null);
});

test("payload is always a Rental customer with trimmed, upper-cased values", () => {
  const body = customerPayload({ ...good, name: " Asha Rao ", gstin: "29abcde1234f1z5" }, "2026-10-31");
  assert.deepEqual(body, { name: "Asha Rao", phone: "98765 43210", email: "asha@example.com", city: "Pune", gstin: "29ABCDE1234F1Z5", type: "Rental", customer_classification: "individual", joined: "2026-10-31" });
});
