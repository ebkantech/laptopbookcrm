/*
 * Light / dark theme. The choice ("light", "dark" or "system") is a
 * per-browser convenience kept in localStorage; the applied theme is the
 * data-theme attribute on <html>, which index.css reads for its colour
 * tokens. Nothing here talks to the server.
 */
const KEY = "v2x-theme";
const MODES = ["light", "dark", "system"];
const listeners = new Set();

export function getThemeMode() {
  try {
    const saved = localStorage.getItem(KEY);
    return MODES.includes(saved) ? saved : "system";
  } catch {
    return "system";
  }
}

const systemDark = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export function resolveTheme(mode = getThemeMode()) {
  if (mode === "light" || mode === "dark") return mode;
  return systemDark() ? "dark" : "light";
}

export function applyTheme(mode = getThemeMode()) {
  const theme = resolveTheme(mode);
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  listeners.forEach((fn) => fn(theme, mode));
  return theme;
}

export function setThemeMode(mode) {
  try { localStorage.setItem(KEY, mode); } catch { /* still applies for this visit */ }
  return applyTheme(mode);
}

export function onThemeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Follow the operating system while the choice is "system".
export function initTheme() {
  applyTheme();
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (getThemeMode() === "system") applyTheme("system");
  });
}
