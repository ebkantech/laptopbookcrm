import test from "node:test";
import assert from "node:assert/strict";
import { filterMessages, insertAt, placeholdersIn, previewText, textProblems } from "./brandingText.js";

test("placeholders are listed once, in order", () => {
  assert.deepEqual(placeholdersIn("Hi {customer}, {invoice} for {customer}"), ["customer", "invoice"]);
});

test("unknown, broken and missing placeholders are reported", () => {
  assert.deepEqual(textProblems("Hi {customer}", ["customer"]), []);
  assert.match(textProblems("Hi {nobody}", ["customer"])[0], /Unknown placeholder: \{nobody\}/);
  assert.match(textProblems("Hi {customer", ["customer"])[0], /isn't closed/);
  assert.match(textProblems("Your code", ["code"], ["code"])[0], /must keep \{code\}/);
});

test("preview fills known placeholders and leaves the rest", () => {
  assert.equal(previewText("Hi {customer} {x}", { customer: "Ravi" }), "Hi Ravi {x}");
});

test("insert at the cursor or over the selection", () => {
  assert.deepEqual(insertAt("Hi !", 3, 3, "{customer}"), ["Hi {customer}!", 13]);
  assert.deepEqual(insertAt("Hi Ravi", 3, 7, "{customer}"), ["Hi {customer}", 13]);
  assert.deepEqual(insertAt("", undefined, undefined, "{a}"), ["{a}", 3]);
});

test("search matches label and wording", () => {
  const list = [{ label: "Payment link", body: "UPI" }, { label: "Repair ready", body: "collect it" }];
  assert.equal(filterMessages(list, "collect").length, 1);
  assert.equal(filterMessages(list, "").length, 2);
});
