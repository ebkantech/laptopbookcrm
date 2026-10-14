// Local Vite proxies /api to Django. Production can override this with the
// same-origin /api path or its configured API origin.
const BASE_URL = import.meta.env.VITE_API_URL || "/api";

let accessToken = localStorage.getItem("cb_access") || null;
let refreshToken = localStorage.getItem("cb_refresh") || null;
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCookie(name) {
  const prefix = `${name}=`;
  const row = document.cookie.split(";").map((cookie) => cookie.trim()).find((cookie) => cookie.startsWith(prefix));
  return row ? decodeURIComponent(row.slice(prefix.length)) : "";
}

async function ensureCsrfCookie() {
  if (readCookie("csrftoken")) return;
  const res = await fetch(`${BASE_URL}/auth/csrf/`, { method: "GET", credentials: "include" });
  if (!res.ok || !readCookie("csrftoken")) throw new Error("Couldn't initialize the secure request token. Reload and try again.");
}

async function responseError(res, fallback) {
  const raw = await res.text();
  let body = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch { /* Django can return an HTML CSRF rejection page. */ }
  const csrfFailure = /CSRF (?:verification failed|cookie not set|token missing|token incorrect|Failed)|Origin checking failed/i.test(`${body.detail || ""} ${raw}`);
  if (csrfFailure) body = { ...body, code: "csrf_failed", detail: "Django rejected this request during CSRF validation." };
  const err = new Error(body.detail || res.statusText || fallback);
  err.status = res.status;
  err.body = body;
  return err;
}

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
  const verb = method.toUpperCase();
  if (UNSAFE_METHODS.has(verb) && !accessToken) await ensureCsrfCookie();
  const doFetch = () =>
    fetch(`${BASE_URL}${path}`, {
      method: verb,
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(UNSAFE_METHODS.has(verb) && readCookie("csrftoken") ? { "X-CSRFToken": readCookie("csrftoken") } : {}),
        ...headers,
      },
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let res = await doFetch();
  if (res.status === 401 && refreshToken) {
    const refreshed = await refreshAccessToken();
    if (refreshed) res = await doFetch();
  }

  if (!res.ok) {
    throw await responseError(res, "Request failed");
  }

  if (res.status === 204) return null;
  return res.json();
}

async function publicRequest(path, { method = "GET", body } = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw await responseError(res, "Request failed");
  }
  return res.json();
}

// Multipart upload (photos) with the same auth + refresh handling as
// request(); the browser sets the multipart boundary itself.
async function upload(path, formData) {
  if (!accessToken) await ensureCsrfCookie();
  const doFetch = () =>
    fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(readCookie("csrftoken") ? { "X-CSRFToken": readCookie("csrftoken") } : {}),
      },
      credentials: "include",
      body: formData,
    });
  let res = await doFetch();
  if (res.status === 401 && refreshToken && (await refreshAccessToken())) res = await doFetch();
  if (!res.ok) {
    throw await responseError(res, "Upload failed");
  }
  return res.json();
}

// A file that needs the staff login (e.g. a handover photo): <img src>
// can't send the Authorization header, so fetch it and hand back an
// object URL. Callers revoke it when done.
async function blobUrl(path) {
  const doFetch = () => fetch(`${BASE_URL}${path}`, { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} });
  let res = await doFetch();
  if (res.status === 401 && refreshToken && (await refreshAccessToken())) res = await doFetch();
  if (!res.ok) throw new Error("Couldn't load file");
  return URL.createObjectURL(await res.blob());
}

// The API pages list endpoints 50 rows at a time. For pickers and lists
// that must show everything (e.g. every product in a dropdown), walk all
// pages and return one flat array. Also accepts an unpaginated response.
async function getAll(path) {
  const sep = path.includes("?") ? "&" : "?";
  const rows = [];
  for (let page = 1; ; page += 1) {
    const data = await request(`${path}${sep}page=${page}`);
    if (!data || !Array.isArray(data.results)) return Array.isArray(data) ? data : rows;
    rows.push(...data.results);
    if (!data.next) return rows;
  }
}

export const api = {
  get: (path) => request(path),
  getAll,
  upload,
  blobUrl,
  // for public pages that point <img> straight at a token-protected URL
  publicUrl: (path) => `${BASE_URL}${path}`,
  post: (path, body) => request(path, { method: "POST", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  del: (path) => request(path, { method: "DELETE" }),
  publicGet: (path) => publicRequest(path),
  publicPost: (path, body) => publicRequest(path, { method: "POST", body }),

  async login(username, password) {
    const res = await fetch(`${BASE_URL}/auth/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
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
            ...(readCookie("csrftoken") ? { "X-CSRFToken": readCookie("csrftoken") } : {}),
          },
          credentials: "include",
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
