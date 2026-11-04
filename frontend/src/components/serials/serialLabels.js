import JsBarcode from "jsbarcode";

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/* One 60 x 40 mm sticker per unit, each with its own serial number as a
 * CODE128 barcode -- a scanner reading it types the serial into any search
 * or picker box. Opens the browser's print dialog (pick the label printer). */
export function printSerialLabels(units, { product, spec, productCode }) {
  const win = window.open("", "_blank", "width=520,height=480");
  if (!win) {
    window.alert("The print window was blocked. Please allow pop-ups for this site and try again.");
    return false;
  }
  const labels = units.map((sn) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    JsBarcode(svg, String(sn), { format: "CODE128", lineColor: "#171634", background: "#FFFFFF", width: 2, height: 42, margin: 2, displayValue: false });
    svg.setAttribute("class", "barcode");
    return `<main class="label"><p class="brand">Vantage Computers</p><p class="product">${esc(product)}</p><p class="spec">${esc(spec)}</p>${svg.outerHTML}<p class="code">S/N ${esc(sn)}</p><p class="details">${esc(productCode)}</p></main>`;
  }).join("");
  win.document.open();
  win.document.write(`<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><title>Serial labels - ${esc(product)}</title><style>
    @page { size: 60mm 40mm; margin: 2mm; }
    * { box-sizing: border-box; } html, body { margin: 0; padding: 0; background: #fff; color: #171634; font-family: Arial, Helvetica, sans-serif; }
    .label { width: 56mm; min-height: 36mm; padding: 1mm; text-align: center; overflow: hidden; break-after: page; break-inside: avoid; }
    .brand { margin: 0 0 1mm; text-align: left; font-size: 8pt; font-weight: 700; }
    .product { margin: 1mm 0; font-size: 10pt; line-height: 1.15; font-weight: 700; overflow-wrap: anywhere; }
    .spec { margin: 0 0 1mm; font-size: 7pt; overflow-wrap: anywhere; }
    .barcode { display: block; width: 100%; max-width: 54mm; height: 12mm; margin: 1mm auto; }
    .code { margin: 0; font-family: monospace; font-size: 9pt; font-weight: 700; }
    .details { margin: 1mm 0 0; font-size: 7pt; }
    @media screen { body { padding: 10px; } .label { border: 1px dashed #aaa; margin-bottom: 8px; } }
  </style></head><body>${labels}</body></html>`);
  win.document.close();
  // printed from here: the Content-Security-Policy blocks inline scripts in the label page
  win.addEventListener("afterprint", () => win.close());
  setTimeout(() => { win.focus(); win.print(); }, 250);
  return true;
}
