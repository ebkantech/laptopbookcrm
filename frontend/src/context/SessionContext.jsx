import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";
import { onStoreChanged } from "../lib/storeEvents";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    if (!api.isAuthenticated()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      const user = await api.get("/users/me/");
      setMe(user);
    } catch {
      api.logout();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  // `me` carries the account's store name (stock_point_name) -- reload it
  // when that store is edited, here or in another tab.
  const myStore = me?.stock_point;
  useEffect(() => {
    if (!myStore) return undefined;
    return onStoreChanged(({ id }) => { if (id === myStore) loadMe(); });
  }, [myStore, loadMe]);

  const login = async (username, password) => {
    await api.login(username, password);
    await loadMe();
  };

  const logout = () => {
    window.history.replaceState({}, "", "/");
    api.logout();
    setMe(null);
  };

  const can = (codename) => !!me && (me.is_superuser || (me.permissions || []).includes(codename));

  return (
    <SessionContext.Provider value={{ me, loading, login, logout, can, refresh: loadMe }}>
      {children}
    </SessionContext.Provider>
  );
}

export const useSession = () => useContext(SessionContext);
