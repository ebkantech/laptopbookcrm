// The signed-in account's place in the role hierarchy, as the sidebar shows
// it. `me.access_level` is decided by the server (accounts.staff.access_level):
// superuser > superadmin (the Owner / Super Admin role) > admin > staff.
const LABELS = { superuser: "Superuser", superadmin: "Superadmin", admin: "Admin", staff: "Staff" };

export function accessLabel(me) {
  if (!me) return "";
  return LABELS[me.access_level] || (me.is_superuser ? LABELS.superuser : LABELS.staff);
}

// Superuser, Super Admin or Admin -- they oversee work rather than being
// given jobs, so worker-only views (e.g. Repairs "My jobs") are hidden.
// Follows the active role: an Admin who switches to a technician role gets them back.
export function isAdminLevel(me) {
  if (!me) return false;
  return ["superuser", "superadmin", "admin"].includes(me.access_level) || !!me.is_superuser;
}
