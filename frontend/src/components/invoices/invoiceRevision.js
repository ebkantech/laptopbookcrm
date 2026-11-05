// Revising an unpaid sale invoice: which invoices may be revised, and the
// sale form's starting lines and stock counts for one. The server enforces
// the same rule (sales.serializers.InvoiceSerializer.update) and moves
// stock only by what the revision changes.

const UNPAID = ["Payment link sent", "Overdue"];

export const canRevise = (invoice, can) =>
  invoice.source === "sale" && UNPAID.includes(invoice.status) && can("invoices.create");

// The invoice's lines as the sale form's editable rows.
export const revisionLines = (invoice, products) =>
  invoice.items.filter((item) => !item.is_discount).map((item) => ({
    productId: String(products.find((p) => p.variants.some((v) => v.id === item.variant))?.id ?? ""),
    variantId: String(item.variant),
    qty: item.qty,
    price: String(item.price),
  }));

// Units of a variant this invoice already holds at a stock point -- they
// count as available to the revision when it stays at the same shop.
export const unitsOnInvoice = (invoice, variantId, stockPointId) =>
  invoice && invoice.stock_point === stockPointId
    ? invoice.items.filter((item) => item.variant === variantId).reduce((n, item) => n + item.qty, 0)
    : 0;
