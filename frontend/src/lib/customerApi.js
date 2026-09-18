const BASE_URL = import.meta.env.VITE_API_URL || "/api";

let csrfToken = null;

async function parseError(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    body = { detail: response.statusText || "Request failed" };
  }
  const firstFieldError = Object.values(body).find((value) => Array.isArray(value));
  const error = new Error(body.detail || firstFieldError?.[0] || "Request failed");
  error.status = response.status;
  error.body = body;
  return error;
}

async function ensureCsrf() {
  if (csrfToken) return csrfToken;
  const response = await fetch(`${BASE_URL}/customer/auth/csrf/`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) throw await parseError(response);
  const data = await response.json();
  csrfToken = data.csrf_token;
  return csrfToken;
}

async function request(path, { method = "GET", body, csrf = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrf) headers["X-CSRFToken"] = await ensureCsrf();
  const response = await fetch(`${BASE_URL}/customer${path}`, {
    method,
    credentials: "include",
    cache: "no-store",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return null;
  return response.json();
}

export const customerApi = {
  csrf: ensureCsrf,
  me: () => request("/me/"),
  dashboard: () => request("/dashboard/"),
  async login(phone, password) {
    const data = await request("/auth/login/", {
      method: "POST", body: { phone, password }, csrf: true,
    });
    // Django rotates the CSRF secret at login. Discard the pre-login token so
    // the next approval/logout request uses the new cookie-bound value.
    csrfToken = null;
    await ensureCsrf();
    return data;
  },
  logout: () => request("/auth/logout/", { method: "POST", csrf: true }),
  tokenInfo: (mode, token) => request(`/auth/${mode}/${encodeURIComponent(token)}/`),
  setPassword: (mode, token, payload) => request(`/auth/${mode}/${encodeURIComponent(token)}/`, {
    method: "POST", body: payload, csrf: true,
  }),
  decideRental: (id, payload) => request(`/rental-approvals/${id}/decision/`, {
    method: "POST", body: payload, csrf: true,
  }),
  decideRepair: (id, payload) => request(`/repair-approvals/${id}/decision/`, {
    method: "POST", body: payload, csrf: true,
  }),
  decideRepairOrder: (id, payload) => request(`/repair-order-approvals/${id}/decision/`, {
    method: "POST", body: payload, csrf: true,
  }),
};
