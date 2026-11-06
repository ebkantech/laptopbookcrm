import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, CONTEXT_RESET_EVENT } from "../lib/api";
import { onStoreChanged } from "../lib/storeEvents";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  // Bumped whenever the active store or role changes: the shell remounts the
  // open page with it, so every page refetches under the new context.
  const [contextVersion, setContextVersion] = useState(0);
  const [switching, setSwitching] = useState(false);

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

  // The server dropped a stored store / role choice the account no longer
  // holds (lib/api.js): reload who we are and refresh the open page.
  useEffect(() => {
    const onReset = () => { loadMe().then(() => setContextVersion((v) => v + 1)); };
    window.addEventListener(CONTEXT_RESET_EVENT, onReset);
    return () => window.removeEventListener(CONTEXT_RESET_EVENT, onReset);
  }, [loadMe]);

  // Switch the store or the role -- each leaves the other as it is. The
  // server validates the choice; /users/me/ then reports the permissions,
  // stores and roles that apply under it.
  const switchContext = async (next) => {
    const previous = api.workContext();
    setSwitching(true);
    api.setWorkContext(next);
    try {
      setMe(await api.get("/users/me/"));
      setContextVersion((v) => v + 1);
    } catch (error) {
      api.setWorkContext(previous);
      throw error;
    } finally {
      setSwitching(false);
    }
  };
  const switchStore = (store) => switchContext({ store });
  const switchRole = (role) => switchContext({ role });

  const login = async (username, password) => {
    await api.login(username, password);
    await loadMe();
  };

  const logout = () => {
    window.history.replaceState({}, "", "/");
    api.logout();
    setMe(null);
  };

  // A module outside the subscription is hidden from everyone, the Super Admin included.
  const inPlan = (codename) => !(me?.subscription?.blocked_prefixes || []).includes(codename.split(".")[0]);
  const can = (codename) => !!me && inPlan(codename) && (me.is_superuser || (me.permissions || []).includes(codename));

  return (
    <SessionContext.Provider value={{ me, loading, login, logout, can, refresh: loadMe, switchStore, switchRole, switching, contextVersion }}>
      {children}
    </SessionContext.Provider>
  );
}

export const useSession = () => useContext(SessionContext);
