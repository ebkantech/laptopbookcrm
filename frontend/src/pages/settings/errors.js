/* Turn a DRF error (api.js puts the parsed body on err.body) into
   { fieldName: "message", _form: "message" } for the Settings forms. */
export function apiErrors(err, fallback = "Something went wrong. Please try again.") {
  const body = err?.body;
  const out = {};
  if (body && typeof body === "object") {
    Object.entries(body).forEach(([key, value]) => {
      if (key === "code") return;
      const msg = Array.isArray(value) ? value.join(" ") : typeof value === "string" ? value : null;
      if (!msg) return;
      out[key === "detail" || key === "non_field_errors" ? "_form" : key] = msg;
    });
  }
  if (!Object.keys(out).length) out._form = err?.message || fallback;
  return out;
}

export const personName = (u) => `${u.first_name || ""} ${u.last_name || ""}`.trim() || u.username;
export const initials = (name) => name.split(/\s+/).filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
