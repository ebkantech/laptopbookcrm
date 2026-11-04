import test from "node:test";
import assert from "node:assert/strict";
import {
  ALL_STORES, activeStoreValue, clearSaved, contextHeaders, dropRefused, readSaved, storeLabel, tokenUserId, writeSaved,
} from "./workContext.js";

const memoryStorage = () => {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
};
const jwt = (payload) => `x.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.y`;

test("only chosen parts become headers; the server default covers the rest", () => {
  assert.deepEqual(contextHeaders({ store: null, role: null }), {});
  assert.deepEqual(contextHeaders({ store: ALL_STORES, role: 4 }), { "X-Active-Store": "all", "X-Active-Role": "4" });
  assert.deepEqual(contextHeaders({ store: 7, role: null }), { "X-Active-Store": "7" });
});

test("a refused store or role is dropped on its own, leaving the other choice alone", () => {
  assert.deepEqual(dropRefused({ store: 7, role: 4 }, "invalid_active_store"), { store: null, role: 4 });
  assert.deepEqual(dropRefused({ store: 7, role: 4 }, "invalid_active_role"), { store: 7, role: null });
  assert.equal(dropRefused({ store: null, role: 4 }, "invalid_active_store"), null);
  assert.equal(dropRefused({ store: 7, role: 4 }, "permission_denied"), null);
});

test("a saved choice is restored only for the account that made it, and cleared on sign-out", () => {
  const storage = memoryStorage();
  writeSaved(storage, "12", { store: 3, role: 9 });
  assert.deepEqual(readSaved(storage, "12"), { store: 3, role: 9 });
  assert.deepEqual(readSaved(storage, "13"), { store: null, role: null });
  clearSaved(storage);
  assert.deepEqual(readSaved(storage, "12"), { store: null, role: null });
  storage.setItem("cb_context", "{broken");
  assert.deepEqual(readSaved(storage, "12"), { store: null, role: null });
});

test("the account id comes from the JWT payload", () => {
  assert.equal(tokenUserId(jwt({ user_id: 12 })), "12");
  assert.equal(tokenUserId("not-a-token"), null);
  assert.equal(tokenUserId(jwt({ sub: "x" })), null);
});

test("switcher labels follow the server's answer", () => {
  const stores = [{ id: 1, name: "Lajpat Nagar" }, { id: 2, name: "Karol Bagh" }];
  const owner = { can_select_all_stores: true, accessible_stores: stores };
  assert.equal(activeStoreValue({ ...owner, active_store: null }), ALL_STORES);
  assert.equal(storeLabel({ ...owner, active_store: null }), "All Stores");
  assert.equal(storeLabel({ ...owner, active_store: 2 }), "Karol Bagh");
  assert.equal(storeLabel({ can_select_all_stores: false, accessible_stores: [], active_store: null }), "No store assigned");
  assert.equal(activeStoreValue({ can_select_all_stores: false, accessible_stores: stores, active_store: 1 }), 1);
});
