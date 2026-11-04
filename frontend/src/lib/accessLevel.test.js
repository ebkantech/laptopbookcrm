import test from "node:test";
import assert from "node:assert/strict";
import { accessLabel } from "./accessLevel.js";

test("each access level the server sends has its own label", () => {
  assert.equal(accessLabel({ access_level: "superuser", is_superuser: true }), "Superuser");
  assert.equal(accessLabel({ access_level: "superadmin" }), "Superadmin");
  assert.equal(accessLabel({ access_level: "admin" }), "Admin");
  assert.equal(accessLabel({ access_level: "staff" }), "Staff");
});

test("the label follows whoever is signed in, and nobody when signed out", () => {
  assert.equal(accessLabel(null), "");
  assert.equal(accessLabel({ access_level: "admin" }), "Admin");
  assert.equal(accessLabel({ access_level: "staff" }), "Staff");
});

test("without an access level a superuser is still never shown as staff", () => {
  assert.equal(accessLabel({ is_superuser: true }), "Superuser");
  assert.equal(accessLabel({ is_superuser: false }), "Staff");
});
