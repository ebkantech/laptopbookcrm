// Local Vite proxies /api to Django. Production can override this with the
// same-origin /api path or its configured API origin.
const BASE_URL = import.meta.env.VITE_API_URL || "/api";

let accessToken = localStorage.getItem("cb_access") || null;
let refreshToken = localStorage.getItem("cb_refresh") || null;

function setTokens(access, refresh) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem("cb_access", access);
  if (refresh) localStorage.setItem("cb_refresh", refresh);
}

function clearTokens() {
  accessToken = null;
  refreshToken = null;
  localStorage.removeItem("cb_access");
  localStorage.removeItem("cb_refresh");
}

async function refreshAccessToken() {
  if (!refreshToken) return false;
  const res = await fetch(`${BASE_URL}/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh: refreshToken }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  // the backend rotates refresh tokens on every use (and blacklists
  // the old one) -- always store whatever refresh token comes back,
  // or the next refresh attempt will fail against a dead token
  setTokens(data.access, data.refresh || refreshToken);
  return true;
}

/**
 * Thin fetch wrapper: attaches the JWT, retries once on a 401 after
 * refreshing the access token, and throws ApiError with the parsed
 * body on any other non-2xx response so callers can show a real
 * message instead of a generic failure.
 */
async function request(path, { method = "GET", body, headers = {} } = {}) {
  const doFetch = () =>
    fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let res = await doFetch();
  if (res.status === 401 && refreshToken) {
    const refreshed = await refreshAccessToken();
    if (refreshed) res = await doFetch();
  }

  if (!res.ok) {
    let detail;
    try {
      detail = await res.json();
    } catch {
      detail = { detail: res.statusText };
    }
    const err = new Error(detail.detail || "Request failed");
    err.status = res.status;
    err.body = detail;
    throw err;
  }

  if (res.status === 204) return null;
  return res.json();
}

async function publicRequest(path, { method = "GET", body } = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail;
    try { detail = await res.json(); } catch { detail = { detail: res.statusText }; }
    const err = new Error(detail.detail || "Request failed");
    err.status = res.status;
    err.body = detail;
    throw err;
  }
  return res.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  del: (path) => request(path, { method: "DELETE" }),
  publicGet: (path) => publicRequest(path),
  publicPost: (path, body) => publicRequest(path, { method: "POST", body }),

  async login(username, password) {
    const res = await fetch(`${BASE_URL}/auth/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error("Invalid username or password");
    const data = await res.json();
    setTokens(data.access, data.refresh);
    return true;
  },

  async logout() {
    // blacklist the refresh token server-side so it can't be reused
    // even if it leaked or was left in browser storage on a shared
    // machine -- best-effort: if this fails (e.g. already offline),
    // still clear local tokens so the user is signed out client-side
    if (refreshToken) {
      try {
        await fetch(`${BASE_URL}/auth/logout/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          },
          body: JSON.stringify({ refresh: refreshToken }),
        });
      } catch {
        // network error on the way out -- fall through to local clear regardless
      }
    }
    clearTokens();
  },

  isAuthenticated() {
    return !!accessToken;
  },
};
