// The signed-in account's place in the role hierarchy, as the sidebar shows
// it. `me.access_level` is decided by the server (accounts.staff.access_level):
// superuser > superadmin (the Owner / Super Admin role) > admin > staff.
const LABELS = { superuser: "Superuser", superadmin: "Superadmin", admin: "Admin", staff: "Staff" };

export function accessLabel(me) {
  if (!me) return "";
  return LABELS[me.access_level] || (me.is_superuser ? LABELS.superuser : LABELS.staff);
}
