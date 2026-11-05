/* One line per product variant on a sale invoice: choosing an item that is
 * already on the invoice raises that line's quantity instead of adding a
 * second line for it. */

export const blankLine = () => ({ productId: "", variantId: "", qty: 1, price: "", serials: [], serialInfo: null });

/* The variant to pre-select when a product is picked on line i: the first one
 * not already on another line (so a second colour/spec gets its own line),
 * else the first variant -- which then merges into its existing line. */
export function variantForProduct(product, lines, i) {
  if (!product?.variants?.length) return null;
  const used = new Set(lines.filter((_, j) => j !== i).map((l) => String(l.variantId)).filter(Boolean));
  return product.variants.find((v) => !used.has(String(v.id))) || product.variants[0];
}

/* Put variant `patch.variantId` on line i. Returns { lines, merged }:
 * merged = { index, qty } when it was already on another line and that line's
 * quantity was raised (line i is then removed). */
export function placeVariant(lines, i, patch) {
  const other = patch.variantId ? lines.findIndex((l, j) => j !== i && String(l.variantId) === String(patch.variantId)) : -1;
  if (other === -1) {
    return { lines: lines.map((l, j) => (j === i ? { ...l, ...patch, serials: [], serialInfo: null } : l)), merged: null };
  }
  const add = Math.max(1, Number(lines[i].qty) || 1);
  const qty = (Number(lines[other].qty) || 0) + add;
  const next = lines.map((l, j) => (j === other ? { ...l, qty } : l)).filter((_, j) => j !== i);
  return { lines: next, merged: { index: other > i ? other - 1 : other, qty } };
}

// The discount as the server works it out: to the nearest rupee.
export const discountOff = (subtotal, percent) => Math.round(subtotal * ((Number(percent) || 0) / 100));
