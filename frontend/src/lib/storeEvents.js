// A shop / channel (catalog.StockPoint) was created or edited. Screens that
// keep stock points or store names in state listen and refetch, so nothing
// shows a stale name or address. Same-tab listeners get a window event;
// other open tabs of the CRM get it through a BroadcastChannel.
export const STORE_CHANGED_EVENT = "vantagecrm:store-changed";
const CHANNEL = "vantagecrm-stores";

let channel = null;
function getChannel() {
  if (!channel && typeof BroadcastChannel !== "undefined") channel = new BroadcastChannel(CHANNEL);
  return channel;
}

export function announceStoreChanged(store) {
  const detail = { store, id: store?.id };
  window.dispatchEvent(new CustomEvent(STORE_CHANGED_EVENT, { detail }));
  try {
    getChannel()?.postMessage(detail);
  } catch {
    // another tab missing one refresh isn't worth failing the save over
  }
}

// Calls handler({ store, id }) for changes made in this tab or another one.
// Returns the unsubscribe function, for a useEffect cleanup.
export function onStoreChanged(handler) {
  const fromWindow = (e) => handler(e.detail || {});
  const fromTab = (e) => handler(e.data || {});
  window.addEventListener(STORE_CHANGED_EVENT, fromWindow);
  const bc = getChannel();
  bc?.addEventListener("message", fromTab);
  return () => {
    window.removeEventListener(STORE_CHANGED_EVENT, fromWindow);
    bc?.removeEventListener("message", fromTab);
  };
}
