// Validation for the "add a new rental customer" panel inside the rental
// agreement form. Mirrors the server's PartySerializer (name, phone, email and
// city are all required) so mistakes are caught before the request is sent.
// Pure functions -- unit-tested in customerValidation.test.js.

export const CUSTOMER_LIMITS = { name: 120, phone: 20, city: 60, email: 254, gstin: 15 };
export const digitsOf = (value) => String(value || "").replace(/\D/g, "");
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// 15 characters: 2 digits state code, 10 char PAN, entity digit, Z, check digit
const GSTIN = /^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$/;

export function validateCustomer(form) {
  const f = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, String(v ?? "").trim()]));
  const errors = {};
  if (!f.name) errors.name = "Enter the customer's name.";
  else if (f.name.length > CUSTOMER_LIMITS.name) errors.name = `Name can be at most ${CUSTOMER_LIMITS.name} characters.`;
  const digits = digitsOf(f.phone);
  if (!f.phone) errors.phone = "Enter the customer's mobile number.";
  else if (digits.length < 10 || digits.length > 15) errors.phone = "Enter a valid phone number with 10 to 15 digits.";
  else if (f.phone.length > CUSTOMER_LIMITS.phone) errors.phone = `Phone can be at most ${CUSTOMER_LIMITS.phone} characters.`;
  if (!f.email) errors.email = "Enter the customer's email address (the agreement is sent there).";
  else if (!EMAIL.test(f.email)) errors.email = "Enter a valid email address.";
  else if (f.email.length > CUSTOMER_LIMITS.email) errors.email = "Email address is too long.";
  if (!f.city) errors.city = "Enter the customer's city.";
  else if (f.city.length > CUSTOMER_LIMITS.city) errors.city = `City can be at most ${CUSTOMER_LIMITS.city} characters.`;
  if (f.gstin && !GSTIN.test(f.gstin.toUpperCase())) errors.gstin = "GSTIN should be 15 characters, e.g. 29ABCDE1234F1Z5 (leave empty if none).";
  return errors;
}

/** An existing customer with the same mobile number (last 10 digits), if any. */
export function findSamePhone(parties, phone) {
  const last10 = digitsOf(phone).slice(-10);
  if (last10.length < 10) return null;
  return parties.find((p) => digitsOf(p.phone).slice(-10) === last10) || null;
}

/** The request body for POST /parties/ -- always a Rental customer. */
export function customerPayload(form, today) {
  const f = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, String(v ?? "").trim()]));
  return {
    name: f.name, phone: f.phone, email: f.email, city: f.city, gstin: f.gstin.toUpperCase(),
    type: "Rental", customer_classification: f.customer_classification || "individual", joined: today,
  };
}
