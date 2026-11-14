/*
 * Inventory list "In stock" column: the colour for a stock quantity.
 *   0      -> red
 *   1 to 3 -> yellow
 *   4+     -> green
 * Returns a tone name; the page maps it to the theme colour tokens.
 */
export function stockTone(quantity) {
  const n = Number(quantity) || 0;
  if (n <= 0) return "red";
  if (n <= 3) return "yellow";
  return "green";
}
