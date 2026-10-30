// Validation for the "New rental agreement" form. Pure functions (no React,
// no DOM) so every rule can be unit-tested -- see agreementValidation.test.js.
// The limits mirror CreateRentalAgreementSerializer on the server, which
// stays the source of truth; this just tells the user *which* field is wrong
// before anything is sent.

export const LIMITS = {
  tenureMax: 120,          // months (10 years)
  feeMax: 1_000_000,       // rupees per device per month
  termsMax: 2000,
  startWindowDays: 366,    // start date may be at most this far back / ahead
};
export const CYCLES = [1, 3, 6, 12];

const FIELD_LABELS = {
  party: "Customer", start: "Start date", tenure_months: "Tenure",
  payment_interval_months: "Recurring payment", auto_invoice: "Automatic invoices",
  terms: "Terms", lines: "Devices", asset_id: "Device", monthly_fee: "Monthly fee",
  asset_tag: "Asset tag", serial_number: "Serial number", brand: "Brand", model_name: "Model", stock: "Item",
};

export const ASSET_LIMITS = { asset_tag: 48, serial_number: 80, brand: 40, model_name: 80 };

const isoToDays = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return null;
  const [y, mo, d] = [+m[1], +m[2], +m[3]];
  const t = Date.UTC(y, mo - 1, d);
  const back = new Date(t);
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== mo - 1 || back.getUTCDate() !== d) return null; // e.g. 2026-02-31
  return Math.round(t / 86_400_000);
};

const wholeNumber = (value) => /^\d+$/.test(String(value ?? "").trim());

/**
 * form: { party, start, tenure, billingCycle, autoInvoice, terms, lines: [{asset_id, monthly_fee}] }
 * ctx:  { today: "YYYY-MM-DD", parties: [...], assetLabel: (id) => string }
 * Returns { errors, warnings, valid } where errors = { party, start, tenure, billingCycle, terms, lines: [{asset, fee}], summary: [..] }.
 */
export function validateAgreement(form, ctx) {
  const errors = { lines: form.lines.map(() => ({})), summary: [] };
  const add = (key, message, summary = message) => { errors[key] = message; errors.summary.push(summary); };

  if (!form.party) add("party", "Choose the customer.");

  const startDay = isoToDays(form.start);
  const todayDay = isoToDays(ctx.today);
  if (!form.start) add("start", "Pick a start date.");
  else if (startDay === null) add("start", "That is not a valid date.");
  else if (todayDay - startDay > LIMITS.startWindowDays) add("start", "Start date is more than a year in the past — check the year.");
  else if (startDay - todayDay > LIMITS.startWindowDays) add("start", "Start date is more than a year ahead — check the year.");

  const tenureText = String(form.tenure ?? "").trim();
  if (!tenureText) add("tenure", "Enter the tenure in months.");
  else if (!wholeNumber(tenureText)) add("tenure", "Tenure must be a whole number of months.");
  else if (+tenureText < 1) add("tenure", "Tenure must be at least 1 month.");
  else if (+tenureText > LIMITS.tenureMax) add("tenure", `Tenure can be at most ${LIMITS.tenureMax} months (${LIMITS.tenureMax / 12} years).`);

  if (!CYCLES.includes(Number(form.billingCycle))) add("billingCycle", "Choose 1, 3, 6 or 12 months.");

  if ((form.terms || "").length > LIMITS.termsMax) add("terms", `Terms are too long (${form.terms.length}/${LIMITS.termsMax} characters).`);

  const seen = new Map();
  let complete = 0;
  form.lines.forEach((line, i) => {
    const hasAsset = !!line.asset_id;
    const feeText = String(line.monthly_fee ?? "").trim();
    const name = hasAsset ? ctx.assetLabel(line.asset_id) : `Device ${i + 1}`;
    if (!hasAsset && !feeText) return; // an untouched spare row is ignored
    if (!hasAsset) {
      errors.lines[i].asset = "Choose the device this fee is for, or remove the row.";
      errors.summary.push(`${name}: choose the device this fee is for, or remove the row.`);
      return;
    }
    if (seen.has(line.asset_id)) {
      errors.lines[i].asset = "This device is already on the agreement.";
      errors.summary.push(`${name} is added twice — remove one row.`);
    } else seen.set(line.asset_id, i);
    if (!feeText) {
      errors.lines[i].fee = "Enter the monthly fee.";
      errors.summary.push(`${name}: enter the monthly fee.`);
    } else if (!wholeNumber(feeText)) {
      errors.lines[i].fee = "Whole rupees only (no decimals or minus sign).";
      errors.summary.push(`${name}: the fee must be whole rupees.`);
    } else if (+feeText < 1) {
      errors.lines[i].fee = "Fee must be more than ₹0.";
      errors.summary.push(`${name}: the fee must be more than ₹0.`);
    } else if (+feeText > LIMITS.feeMax) {
      errors.lines[i].fee = `Fee can be at most ₹${LIMITS.feeMax.toLocaleString("en-IN")} a month.`;
      errors.summary.push(`${name}: the fee is above the ₹${LIMITS.feeMax.toLocaleString("en-IN")} limit.`);
    }
    if (!errors.lines[i].asset && !errors.lines[i].fee) complete += 1;
  });
  if (!form.lines.some((l) => l.asset_id)) {
    errors.devices = "Add at least one device.";
    errors.summary.push("Add at least one device with its monthly fee.");
  }

  const warnings = [];
  const party = ctx.parties.find((p) => String(p.id) === String(form.party));
  if (party && form.autoInvoice) {
    if (!party.phone && !party.email) warnings.push(`${party.name} has no phone number or email on file, so automatic invoices cannot reach them. Add contact details on the Parties page.`);
    else if (!party.phone) warnings.push(`${party.name} has no phone number, so invoices will go by email only (no WhatsApp).`);
    else if (!party.email) warnings.push(`${party.name} has no email on file, so invoices will go by WhatsApp only.`);
  }
  if (startDay !== null && todayDay !== null && startDay < todayDay - 31) {
    warnings.push("This start date is more than a month ago. Invoices for the months already past will be raised one per day until they catch up.");
  }
  if (CYCLES.includes(Number(form.billingCycle)) && wholeNumber(tenureText) && Number(form.billingCycle) > +tenureText && +tenureText >= 1) {
    warnings.push(`The cycle is longer than the tenure, so a single invoice will cover all ${tenureText} month${+tenureText > 1 ? "s" : ""}.`);
  }

  const hasLineError = errors.lines.some((l) => l.asset || l.fee);
  const valid = errors.summary.length === 0 && complete > 0 && !hasLineError;
  return { errors, warnings, valid };
}

/** The "register a device" mini-form. Returns { errors: {field: message}, summary: [..] }. */
export function validateAssetDraft(draft) {
  const errors = {};
  const need = { serial_number: "Enter the serial number printed on the unit.", brand: "Enter the brand.", model_name: "Enter the model." };
  Object.entries(need).forEach(([key, message]) => { if (!String(draft[key] ?? "").trim()) errors[key] = message; });
  Object.entries(ASSET_LIMITS).forEach(([key, max]) => {
    if (!errors[key] && String(draft[key] ?? "").trim().length > max) errors[key] = `${FIELD_LABELS[key]} can be at most ${max} characters.`;
  });
  return { errors, summary: Object.values(errors) };
}

/** The "rent out from inventory" mini-form. */
export function validateInventoryPick({ stockId, serial, tag }) {
  const errors = {};
  if (!stockId) errors.stock = "Pick the laptop from the list.";
  if (!String(serial ?? "").trim()) errors.serial_number = "Enter the serial number printed on this unit.";
  else if (String(serial).trim().length > ASSET_LIMITS.serial_number) errors.serial_number = `Serial number can be at most ${ASSET_LIMITS.serial_number} characters.`;
  if (String(tag ?? "").trim().length > ASSET_LIMITS.asset_tag) errors.asset_tag = `Asset tag can be at most ${ASSET_LIMITS.asset_tag} characters.`;
  return { errors, summary: Object.values(errors) };
}

/**
 * Turn whatever the API (or the network) threw into something a person can act on.
 * Returns { message, fields } -- fields maps our form keys to a message so they can be
 * shown next to the input; message is the summary line.
 */
export function describeServerError(err) {
  const body = err?.body && typeof err.body === "object" ? err.body : {};
  if (err?.status === undefined && !Object.keys(body).length) {
    if (/failed to fetch|networkerror|load failed/i.test(err?.message || "")) {
      return { message: "Couldn't reach the server. Check your internet connection and try again — nothing was saved.", fields: {} };
    }
    return { message: err?.message || "Something went wrong. Nothing was saved.", fields: {} };
  }
  if (err.status >= 500) return { message: "The server hit an error and nothing was saved. Try again in a moment; if it keeps happening, tell your admin.", fields: {} };
  if (err.status === 401) return { message: "Your session has expired. Sign in again, then retry.", fields: {} };
  if (err.status === 403) return { message: body.detail || "You do not have permission to create rental agreements.", fields: {} };

  const fields = {};
  const lines = [];
  const text = (v) => (Array.isArray(v) ? v.map(text).filter(Boolean).join(" ") : (v && typeof v === "object") ? Object.entries(v).map(([k, x]) => `${FIELD_LABELS[k] || k}: ${text(x)}`).join(" ") : String(v ?? ""));
  Object.entries(body).forEach(([key, value]) => {
    if (key === "detail" || key === "code") return;
    if (key === "non_field_errors") { lines.push(text(value)); return; }
    if (key === "lines" && Array.isArray(value) && value.some((x) => x && typeof x === "object" && !Array.isArray(x))) {
      value.forEach((row, i) => {
        const msg = text(row);
        if (msg) { lines.push(`Device ${i + 1} — ${msg}`); (fields.lines ||= {})[i] = row; }
      });
      return;
    }
    const label = FIELD_LABELS[key];
    const msg = text(value);
    if (!msg) return;
    fields[key] = msg;
    lines.push(label ? `${label}: ${msg}` : msg);
  });
  if (body.detail) lines.unshift(String(body.detail));
  return { message: lines.join(" ") || err.message || "The agreement could not be saved.", fields };
}
