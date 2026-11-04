// Pure helpers for Inventory -> Costs: the sheet you download, fill in and upload again.
// Columns: code, item, details, selling price, cost. Only `code` and `cost` are read back.

const quote = (v) => {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function toSheet(review) {
  const rows = [["code", "item", "details", "selling_price", "cost"]];
  for (const v of review?.variants || []) rows.push([v.code, v.product, [v.spec, v.colour].filter(Boolean).join(" / "), v.sell_price, ""]);
  for (const p of review?.parts || []) rows.push([p.code, p.name, "spare part", "", ""]);
  return rows.map((r) => r.map(quote).join(",")).join("\r\n") + "\r\n";
}

// Minimal CSV reader: quoted fields, doubled quotes, commas / tabs / semicolons as separators.
function splitRows(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  const sep = /\t/.test(text.split(/\r?\n/)[0] || "") ? "\t" : /;/.test(text.split(/\r?\n/)[0] || "") && !/,/.test(text.split(/\r?\n/)[0] || "") ? ";" : ",";
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') inQuotes = false;
      else field += ch;
    } else if (ch === '"') inQuotes = true;
    else if (ch === sep) { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += ch;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

const money = (s) => String(s ?? "").replace(/[₹,\s]/g, "").replace(/^rs\.?/i, "");

/** -> { rows: [{code, cost}], skipped: n, problems: [text] }. Rows with an empty cost are skipped, not errors. */
export function fromSheet(text) {
  const all = splitRows(String(text || "").replace(/^﻿/, ""));
  if (!all.length) return { rows: [], skipped: 0, problems: ["The sheet is empty."] };
  const head = all[0].map((h) => h.trim().toLowerCase());
  let codeAt = head.findIndex((h) => ["code", "sku", "variant code", "part code"].includes(h));
  let costAt = head.findIndex((h) => ["cost", "purchase cost", "cost price", "unit cost"].includes(h));
  let body = all.slice(1);
  if (codeAt < 0 || costAt < 0) {
    // no header row: two columns, code then cost
    if (all[0].length < 2) return { rows: [], skipped: 0, problems: ["Use two columns -- code and cost -- or the downloaded sheet."] };
    codeAt = 0; costAt = all[0].length >= 5 ? 4 : 1; body = all;
  }
  const rows = [], problems = [];
  let skipped = 0;
  body.forEach((r, n) => {
    const line = n + (body === all ? 1 : 2);
    const code = (r[codeAt] || "").trim();
    const raw = money(r[costAt]);
    if (!code && !raw) return;
    if (!raw) { skipped += 1; return; }
    if (!code) { problems.push(`Line ${line}: a cost with no code.`); return; }
    if (!/^\d+$/.test(raw) || Number(raw) < 1) { problems.push(`Line ${line} (${code}): "${r[costAt]}" isn't a whole number of rupees.`); return; }
    rows.push({ code, cost: Number(raw) });
  });
  return { rows, skipped, problems };
}
