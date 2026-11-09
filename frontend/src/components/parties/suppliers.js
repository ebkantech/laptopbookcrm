import { api } from "../../lib/api";

// Parties of type Supplier, loaded once per page visit (Add stock, tagging old stock).
let cache = null;
export function loadSuppliers(force = false) {
  if (!cache || force) {
    cache = api.getAll("/parties/").then((all) => all.filter((p) => p.type === "Supplier").sort((a, b) => a.name.localeCompare(b.name)))
      .catch((e) => { cache = null; throw e; });
  }
  return cache;
}
