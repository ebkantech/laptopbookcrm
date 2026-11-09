// Same rules as the server (backend/crmbook_backend/phones.py), so a bad
// number is caught as it's typed. Returns "" when the number is fine.
export function phoneError(value) {
  const raw = String(value || "").trim();
  if (!raw) return "Enter the customer's mobile number.";
  if (!/^\+?[\d\s\-().]+$/.test(raw)) return "A phone number can only have digits (and + at the start).";
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("00")) return "Don't start the number with 00. Type the 10-digit mobile number, or + and the country code for a foreign number.";
  if (raw.startsWith("+") && !digits.startsWith("91")) {
    return digits.length >= 8 && digits.length <= 15 && digits[0] !== "0" ? "" : "Enter a foreign number as + country code and number, e.g. +971 50 123 4567.";
  }
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length !== 10) return `A mobile number has 10 digits — this one has ${digits.length}. For a foreign number type + and the country code.`;
  if (!"6789".includes(digits[0])) return "An Indian mobile number starts with 6, 7, 8 or 9.";
  if (new Set(digits).size === 1) return "That doesn't look like a real number.";
  return "";
}
