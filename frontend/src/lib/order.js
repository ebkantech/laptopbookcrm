import { useCallback, useState } from "react";

/* Which way a ledger reads. "asc" = oldest at the top, "desc" = newest at the
 * top. The running balance of a book is always worked out oldest-first; only
 * the display order flips. The choice is remembered per ledger in this browser. */
export const flipOrder = (dir) => (dir === "asc" ? "desc" : "asc");

export function orderRows(rows, dir, naturalDir = "asc") {
  return dir === naturalDir ? rows : [...rows].reverse();
}

export function useOrder(key, fallback = "asc") {
  const [dir, setDir] = useState(() => {
    try {
      const saved = window.localStorage.getItem(`crm.order.${key}`);
      return saved === "asc" || saved === "desc" ? saved : fallback;
    } catch {
      return fallback;
    }
  });
  const set = useCallback((next) => {
    setDir(next);
    try { window.localStorage.setItem(`crm.order.${key}`, next); } catch { /* private window / blocked storage: keep it for this visit only */ }
  }, [key]);
  return [dir, set];
}
