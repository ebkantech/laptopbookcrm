import test from "node:test";
import assert from "node:assert/strict";
import { appEnabled, grantedCount, groupByApp, toggleAppCodes } from "./appAccess.js";

const app = { key: "repairs", label: "Repairs", view: "repairs.view", permissions: ["repairs.manage", "repairs.view"] };
const role = (codes, slug = "x") => ({ slug, permission_codes: codes });

test("groupByApp attaches permission objects and drops empty apps", () => {
  const out = groupByApp([app, { key: "e", label: "E", view: null, permissions: [] }], [{ codename: "repairs.view", description: "View" }]);
  assert.equal(out.length, 1);
  assert.equal(out[0].perms[0].description, "repairs.manage");
  assert.equal(out[0].perms[1].description, "View");
});

test("appEnabled / grantedCount", () => {
  assert.equal(appEnabled(role(["repairs.view"]), app), true);
  assert.equal(appEnabled(role(["repairs.manage"]), app), false);
  assert.equal(appEnabled(role([], "owner"), app), true);
  assert.equal(grantedCount(role(["repairs.manage"]), app), 1);
  assert.equal(grantedCount(role([], "owner"), app), 2);
});

test("toggleAppCodes turns an app on with just view, and off removing everything of that app", () => {
  assert.deepEqual(toggleAppCodes(role(["leads.view"]), app), ["leads.view", "repairs.view"]);
  assert.deepEqual(toggleAppCodes(role(["leads.view", "repairs.view", "repairs.manage"]), app), ["leads.view"]);
});
