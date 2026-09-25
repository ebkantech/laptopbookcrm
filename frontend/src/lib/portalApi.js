const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

let portalToken = localStorage.getItem("cb_portal_token") || null;

function setPortalToken(token) {
  portalToken = token;
  if (token) localStorage.setItem("cb_portal_token", token);
}

function clearPortalToken() {
  portalToken = null;
  localStorage.removeItem("cb_portal_token");
}

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(portalToken ? { Authorization: `Portal ${portalToken}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail;
    try { detail = await res.json(); } catch { detail = { detail: res.statusText }; }
    const err = new Error(detail.detail || "Request failed");
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

export const portalApi = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),

  // public, no token needed yet
  inviteStatus: (token) => request(`/portal/invite-status/${token}/`),
  verify: (token, otp) => request(`/portal/verify/`, { method: "POST", body: { token, otp } }),

  hasSession: () => !!portalToken,
  setSession: setPortalToken,
  clearSession: clearPortalToken,
};
