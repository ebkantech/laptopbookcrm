// The active store and active role a staff account works in. Only the
// CHOICE lives in the browser (so it survives a refresh); the server checks
// it against the account's own assignments on every request
// (accounts.context) and answers 403 with one of REFUSAL_CODES if it no
// longer holds -- then that choice is dropped and the server default used.

const STORAGE_KEY = "cb_context";
export const ALL_STORES = "all";
export const REFUSAL_CODES = { invalid_active_store: "store", invalid_active_role: "role" };

export const emptyContext = () => ({ store: null, role: null });

// The headers for a context; nothing for a part not chosen (server default).
export function contextHeaders(context) {
  const headers = {};
  if (context.store !== null && context.store !== undefined) headers["X-Active-Store"] = String(context.store);
  if (context.role !== null && context.role !== undefined) headers["X-Active-Role"] = String(context.role);
  return headers;
}

// A context minus the part the server refused, or null if `code` isn't a refusal.
export function dropRefused(context, code) {
  const part = REFUSAL_CODES[code];
  if (!part || context[part] === null) return null;
  return { ...context, [part]: null };
}

// The signed-in account's id from its JWT, so a saved choice is only ever
// restored for the account that made it.
export function tokenUserId(token) {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const id = JSON.parse(atob(payload)).user_id;
    return id === undefined || id === null ? null : String(id);
  } catch {
    return null;
  }
}

export function readSaved(storage, userId) {
  if (!userId) return emptyContext();
  try {
    const saved = JSON.parse(storage.getItem(STORAGE_KEY) || "null");
    if (!saved || String(saved.user) !== String(userId)) return emptyContext();
    return { store: saved.store ?? null, role: saved.role ?? null };
  } catch {
    return emptyContext();
  }
}

export function writeSaved(storage, userId, context) {
  try {
    if (userId) storage.setItem(STORAGE_KEY, JSON.stringify({ user: String(userId), ...context }));
  } catch {
    // a per-browser convenience: without it the server default applies after a refresh
  }
}

export function clearSaved(storage) {
  try {
    storage.removeItem(STORAGE_KEY);
  } catch {
    // nothing saved to clear
  }
}

// What the switchers show, from the server's own answer (GET /users/me/).
export function activeStoreValue(me) {
  if (!me) return null;
  return me.active_store === null && me.can_select_all_stores ? ALL_STORES : me.active_store;
}

export function storeLabel(me) {
  const value = activeStoreValue(me);
  if (value === ALL_STORES) return "All Stores";
  return (me?.accessible_stores || []).find((s) => s.id === value)?.name || (value === null ? "No store assigned" : "Store");
}
