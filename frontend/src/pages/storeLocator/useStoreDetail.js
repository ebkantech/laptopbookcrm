import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

// One store's GET /stock-points/<id>/locator/ payload, cached per id; a
// slower reply for a store the user already left never replaces the current one.
export function useStoreDetail() {
  const [state, setState] = useState({ data: null, error: null, loading: false });
  const seq = useRef(0);
  const cache = useRef(new Map());
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const load = useCallback(async (id, { force = false } = {}) => {
    const mine = ++seq.current;
    const cached = !force && cache.current.get(id);
    if (cached) {
      setState({ data: cached, error: null, loading: false });
      return;
    }
    setState((s) => ({ data: force ? s.data : null, error: null, loading: true }));
    try {
      const data = await api.get(`/stock-points/${id}/locator/`);
      cache.current.set(id, data);
      // a slower reply for a store the user already left must not win
      if (alive.current && mine === seq.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (alive.current && mine === seq.current) setState({ data: null, error, loading: false });
    }
  }, []);

  // A store's own details changed (it was edited): show them at once in the
  // open detail and the cache, ahead of the refetch that follows.
  const patchStore = useCallback((store) => {
    const hit = cache.current.get(store.id);
    if (hit) cache.current.set(store.id, { ...hit, stock_point: store });
    setState((s) => (s.data?.stock_point?.id === store.id ? { ...s, data: { ...s.data, stock_point: store } } : s));
  }, []);

  const cancel = useCallback(() => { seq.current += 1; }, []);
  const clear = useCallback(() => cache.current.clear(), []);
  return { state, load, cancel, clear, patchStore };
}
