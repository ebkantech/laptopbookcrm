import { C } from "../../lib/theme";

/* One vocabulary for rental agreement + approval-link states, so the card,
 * the link panel and the history never call the same thing two names.
 * "Changes requested" is deliberately its own colour: it is neither an
 * approval nor a rejection. */
export const RENTAL_STATUS = {
  draft: { label: "Draft", color: C.inkSoft },
  pending_approval: { label: "Awaiting customer", color: C.amber },
  approved: { label: "Approved", color: C.green },
  rejected: { label: "Rejected", color: C.carbon },
  active: { label: "Active", color: C.green },
  closed: { label: "Closed", color: C.inkSoft },
  cancelled: { label: "Cancelled", color: C.inkSoft },
};

export const APPROVAL_STATUS = {
  not_sent: { label: "Link not sent", color: C.inkSoft },
  pending: { label: "Awaiting response", color: C.amber },
  approved: { label: "Approved", color: C.green },
  rejected: { label: "Rejected", color: C.carbon },
  changes_requested: { label: "Changes requested", color: C.stamp },
  expired: { label: "Link expired", color: C.inkSoft },
  revoked: { label: "Link revoked", color: C.inkSoft },
};

export const statusOf = (map, key) => map[key] || { label: key ? key.replace(/_/g, " ") : "—", color: C.inkSoft };

export const fmtDateTime = (value) =>
  value
    ? new Date(value).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "—";
