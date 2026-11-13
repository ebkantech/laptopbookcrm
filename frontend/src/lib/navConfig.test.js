import { test } from "node:test";
import assert from "node:assert/strict";
import { visibleCategories, visibleModules, quickLinks, categoryOf, canOpen } from "./navConfig.js";

const staff = { permissions: ["repairs.view", "leads.view"], subscription: {} };
const owner = { is_superuser: true, permissions: [], subscription: { blocked_prefixes: ["broadcast"] } };

test("staff see only what their permissions allow, plus Settings", () => {
  assert.deepEqual(visibleModules(staff), ["leads", "repairs", "settings"]);
  assert.deepEqual(visibleCategories(staff).map((c) => c.id), ["service"]);
});

test("superuser sees everything except subscription-blocked apps", () => {
  const mods = visibleModules(owner);
  assert.ok(mods.includes("accounting") && mods.includes("home"));
  assert.ok(!mods.includes("broadcast"));
  assert.equal(canOpen(owner, "broadcast"), false);
});

test("admin-only settings links are hidden from staff", () => {
  assert.deepEqual(quickLinks(staff, "settings").map((q) => q.label), ["Profile", "My password"]);
  assert.equal(quickLinks(owner, "settings").length, 7);
});

test("no account sees nothing", () => {
  assert.deepEqual(visibleModules(null), []);
  assert.equal(categoryOf("repairs").id, "service");
  assert.equal(categoryOf("rentals").id, "service");
  assert.equal(categoryOf("warranty").id, "warranty");
});
