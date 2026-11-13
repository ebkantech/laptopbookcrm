/*
 * The app's navigation, as data. The header's mega-menus, the context bar,
 * the mobile drawer and the command palette all read from here, so they
 * always list exactly the same permission-filtered modules.
 *
 * Each module's `perm` is unchanged from the old sidebar: a role that can't
 * act on a section never sees it listed. A superuser always does (unless the
 * subscription blocks that app). Pure functions -- no React, no API calls.
 */

// id -> { label, perm, description, quick: [{ label, search }] }
export const MODULES = {
  home: { label: "Dashboard", perm: "dashboard.view", description: "Today's numbers, alerts and activity" },
  inventory: { label: "Inventory", perm: "inventory.edit", description: "Products, variants, stock and barcodes" },
  storeLocator: { label: "Store Locator", perm: "storelocator.view", description: "Stores, staff on duty and branch P&L" },
  invoices: {
    label: "Sales & Invoices", perm: "invoices.view", description: "Bills, payments, returns and warranty cards",
  },
  parties: {
    label: "Parties", perm: "parties.view", description: "Customers, suppliers, statements and chats",
    quick: [{ label: "Customers", search: "" }, { label: "Suppliers", search: "?tab=suppliers" }],
  },
  rentals: { label: "Rentals", perm: "rentals.view", description: "Agreements, rent due and returns" },
  leads: { label: "On-site Service", perm: "leads.view", description: "Field jobs from enquiry to bill" },
  repairs: { label: "Repairs & Service", perm: "repairs.view", description: "Workshop tickets, estimates and parts" },
  warranty: { label: "Warranty", perm: "warranty.manage", description: "Warranty registrations and claims" },
  accounting: { label: "Accounting", perm: "cashbook.view", description: "Cash book, bank book, expenses, advances" },
  reports: { label: "Reports", perm: "reports.view", description: "Financial, sales, rental and repair reports" },
  broadcast: { label: "Broadcast", perm: "broadcast.send", description: "Messages to customer groups" },
  settings: {
    label: "Settings", description: "Your account, staff, roles and business details",
    quick: [
      { label: "Profile", search: "?tab=profile" },
      { label: "My password", search: "?tab=password" },
      { label: "Staff management", search: "?tab=staff", admin: true },
      { label: "Roles & access", search: "?tab=roles", admin: true },
      { label: "Staff alerts", search: "?tab=notifications", admin: true },
      { label: "Business & messages", search: "?tab=business", admin: true },
      { label: "Subscription", search: "?tab=subscription", admin: true },
    ],
  },
};

// The header's categories. A category with one visible module opens it
// directly; one with several opens a mega-menu.
export const CATEGORIES = [
  { id: "overview", label: "Dashboard", crumb: "Overview", modules: ["home"] },
  { id: "sales", label: "Sales", blurb: "Selling, billing and the people you deal with", modules: ["invoices", "parties", "broadcast"] },
  { id: "service", label: "Service", blurb: "Repairs in the shop, jobs on site and laptops on rent", modules: ["leads", "repairs", "rentals"] },
  { id: "warranty", label: "Warranty", crumb: "After-sales", modules: ["warranty"] },
  { id: "assets", label: "Assets", blurb: "Stock and the stores and channels that hold it", modules: ["inventory", "storeLocator"] },
  { id: "finance", label: "Finance", blurb: "Money in, money out, and the reports", modules: ["accounting", "reports"] },
];

export function canOpen(me, id) {
  const mod = MODULES[id];
  if (!me || !mod) return false;
  if (!mod.perm) return true;
  const blocked = me.subscription?.blocked_prefixes || [];
  const perms = me.permissions || [];
  const holds = (code) => !blocked.includes(code.split(".")[0]) && (me.is_superuser || perms.includes(code));
  return Array.isArray(mod.perm) ? mod.perm.some(holds) : holds(mod.perm);
}

// Same rule Settings.jsx uses for its admin-only tabs.
export const isStaffAdmin = (me) => !!me?.is_superuser || !!me?.sees_all_stores || (me?.permissions || []).includes("roles.manage");

export function quickLinks(me, id) {
  const admin = isStaffAdmin(me);
  return (MODULES[id]?.quick || []).filter((q) => !q.admin || admin);
}

export function visibleCategories(me) {
  return CATEGORIES.map((cat) => ({ ...cat, modules: cat.modules.filter((id) => canOpen(me, id)) }))
    .filter((cat) => cat.modules.length > 0);
}

// Every module this account may open, in menu order, Settings last.
export function visibleModules(me) {
  if (!me) return [];
  return [...visibleCategories(me).flatMap((c) => c.modules), "settings"];
}

export function categoryOf(id) {
  return CATEGORIES.find((c) => c.modules.includes(id)) || null;
}
