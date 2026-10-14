export const PARTY_CHANGED_EVENT = "vantagecrm:party-changed";

export function announcePartyChanged(party, deleted = false) {
  window.dispatchEvent(new CustomEvent(PARTY_CHANGED_EVENT, {
    detail: { party, id: party?.id, deleted },
  }));
}
