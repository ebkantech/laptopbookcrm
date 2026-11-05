// Plain helpers for the Copilot panel, kept apart from React so they can be tested.

const FIELD_LABELS = {
  pay_method: "Payment method", payment_reference: "Reference", paid_on: "Paid on", reason: "Reason",
  channel: "Channel", body: "Message", status: "New stage", assigned_to: "Assign to (staff id)",
  override_reason: "Override reason", staff_confirmed_upi: "UPI confirmed with customer", name: "Name",
  type: "Type", phone: "Phone", email: "Email", city: "City", gstin: "GSTIN", date: "Date",
  particulars: "Particulars", amount: "Amount",
};

// Every value that will be sent, in words, for the confirm card.
export function actionFields(body) {
  return Object.entries(body || {}).map(([key, value]) => ({
    key,
    label: FIELD_LABELS[key] || key,
    value: typeof value === "boolean" ? (value ? "Yes" : "No") : String(value),
  }));
}

export const ACTION_STATUS = {
  proposed: { label: "Waiting for you", tone: "amber" },
  done: { label: "Done", tone: "green" },
  failed: { label: "Failed", tone: "carbon" },
  rejected: { label: "Rejected", tone: "inkSoft" },
  expired: { label: "Expired", tone: "inkSoft" },
  executing: { label: "Running", tone: "blue" },
};

export const CHANNEL_LABELS = { whatsapp: "WhatsApp", email: "Email", portal: "Customer portal" };

// Chat messages and action cards in the order they happened.
export function mergeTimeline(messages, actions) {
  const rows = [
    ...(messages || []).map((message) => ({ kind: "message", at: message.created_at, item: message })),
    ...(actions || []).map((action) => ({ kind: "action", at: action.created_at, item: action })),
  ];
  return rows.sort((a, b) => new Date(a.at) - new Date(b.at));
}

// Models sometimes write **bold** or `code` anyway: show it as text, without the symbols.
export function plainReply(text) {
  return String(text || "")
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/^\s*\* /gm, "- ");
}
