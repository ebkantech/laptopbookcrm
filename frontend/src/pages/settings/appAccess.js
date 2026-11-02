// Pure helpers for the Roles & access screen: access is shown app by app.

export function groupByApp(apps, permissions) {
  const byCode = new Map((permissions || []).map((p) => [p.codename, p]));
  return (apps || [])
    .map((app) => ({ ...app, perms: app.permissions.map((code) => byCode.get(code) || { codename: code, description: code }) }))
    .filter((app) => app.perms.length);
}

export function appEnabled(role, app) {
  return role.slug === "owner" || (!!app.view && role.permission_codes.includes(app.view));
}

export function grantedCount(role, app) {
  return role.slug === "owner" ? app.permissions.length : app.permissions.filter((c) => role.permission_codes.includes(c)).length;
}

// Switch an app on (just the "can open it" permission) or off (every permission of that app).
export function toggleAppCodes(role, app) {
  const current = role.permission_codes;
  if (appEnabled(role, app)) return current.filter((c) => !app.permissions.includes(c));
  return app.view && !current.includes(app.view) ? [...current, app.view] : current;
}
