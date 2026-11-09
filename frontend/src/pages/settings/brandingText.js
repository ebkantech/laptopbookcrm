// Helpers for Settings -> Business & messages (kept free of React so they can be tested).

const FIELD = /\{([^{}]*)\}/g;

/** The {placeholders} a text uses, in order, without repeats. */
export function placeholdersIn(text) {
  const seen = [];
  for (const m of String(text || "").matchAll(FIELD)) if (!seen.includes(m[1])) seen.push(m[1]);
  return seen;
}

/** What's wrong with a wording before it's saved -- the server checks the same. */
export function textProblems(text, allowed, required = []) {
  const value = String(text || "");
  const problems = [];
  const stripped = value.replace(FIELD, "");
  if (stripped.includes("{") || stripped.includes("}")) problems.push("A { or } isn't closed. Use {placeholder} with both braces.");
  const unknown = placeholdersIn(value).filter((p) => !allowed.includes(p));
  if (unknown.length) problems.push(`Unknown placeholder${unknown.length > 1 ? "s" : ""}: ${unknown.map((u) => `{${u}}`).join(", ")}.`);
  const missing = required.filter((r) => !placeholdersIn(value).includes(r));
  if (value && missing.length) problems.push(`This message must keep ${missing.map((m) => `{${m}}`).join(", ")}.`);
  return problems;
}

/** The text as a customer would see it, with the sample values filled in. */
export function previewText(text, samples) {
  return String(text || "").replace(FIELD, (whole, name) => (name in samples ? String(samples[name]) : whole));
}

/** Put `token` into `text` where the cursor is (or replace the selection); returns [text, new cursor]. */
export function insertAt(text, start, end, token) {
  const value = String(text || "");
  const a = Math.max(0, Math.min(start ?? value.length, value.length));
  const b = Math.max(a, Math.min(end ?? a, value.length));
  return [value.slice(0, a) + token + value.slice(b), a + token.length];
}

/** Messages whose label, description, group or wording mention the search. */
export function filterMessages(messages, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return messages;
  return messages.filter((m) => [m.label, m.when, m.group, m.body, m.subject, m.email_body].some((v) => String(v || "").toLowerCase().includes(q)));
}
