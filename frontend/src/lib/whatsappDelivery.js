/* What a WhatsApp send reported, in staff's words. "sent" only when Meta
 * accepted the message and returned its id. */
export function whatsappSendNote(delivery) {
  if (!delivery) return null;
  if (delivery.status === "sent") return { ok: true, text: `Sent through the WhatsApp API${delivery.template ? ` (template ${delivery.template})` : ""} — Meta accepted it. Delivery to the phone is confirmed in the customer's chat.` };
  if (delivery.status === "simulated") return { ok: false, text: "WhatsApp API isn't switched on (console mode) — nothing was sent. Use the manual WhatsApp button." };
  if (delivery.status === "skipped") return { ok: false, text: `Not sent: ${delivery.reason || "no phone number on file"}.` };
  return { ok: false, text: `Not sent: ${delivery.reason || "the WhatsApp API rejected the message"}. You can retry, or send it manually.` };
}
