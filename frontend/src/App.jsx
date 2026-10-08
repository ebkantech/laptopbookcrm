import { lazy, Suspense, useState } from "react";
import {
  LayoutDashboard, Package, Receipt, Users, Repeat2, Landmark, Megaphone,
  Wrench, LogOut, Settings as SettingsIcon, BadgeCheck, BarChart3,
} from "lucide-react";
import { C, F, APP_NAME, APP_VERSION } from "./lib/theme";
import { SessionProvider, useSession } from "./context/SessionContext";
import { Spinner } from "./components/Atoms";
import AnimatedGradientBackground from "./components/AnimatedGradientBackground";
const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Inventory = lazy(() => import("./pages/Inventory"));
const Invoices = lazy(() => import("./pages/Invoices"));
const Parties = lazy(() => import("./pages/Parties"));
const Rentals = lazy(() => import("./pages/Rentals"));
const Repairs = lazy(() => import("./pages/Repairs"));
const Accounting = lazy(() => import("./pages/Accounting"));
const Broadcast = lazy(() => import("./pages/Broadcast"));
const Settings = lazy(() => import("./pages/Settings"));
const Warranty = lazy(() => import("./pages/Warranty"));
const Reports = lazy(() => import("./pages/Reports"));
const RepairApproval = lazy(() => import("./pages/RepairApproval"));
const RentalApproval = lazy(() => import("./pages/RentalApproval"));
const RepairOrderApproval = lazy(() => import("./pages/RepairOrderApproval"));
const PortalApp = lazy(() => import("./PortalApp"));

// Grouped the way the redesign reference groups its own nav (Overview /
// Manage / Admin) -- each item's optional `perm` is checked against the
// signed-in user's permissions (visibleNavGroups below) so a role that
// can't act on a section never sees it listed at all, not even greyed
// out. A superuser (or a codename with no listed permission requirement,
// like Dashboard/Settings) always sees the item.
const NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { id: "home", label: "Dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "Manage",
    items: [
      { id: "inventory", label: "Inventory", icon: Package, perm: "inventory.edit" },
      { id: "invoices", label: "Sales & Invoices", icon: Receipt, perm: "invoices.view" },
      { id: "parties", label: "Parties", icon: Users, perm: "parties.view" },
      { id: "rentals", label: "Rentals", icon: Repeat2, perm: "rentals.view" },
      { id: "repairs", label: "Repairs & Service", icon: Wrench, perm: "repairs.view" },
      { id: "warranty", label: "Warranty", icon: BadgeCheck, perm: "warranty.manage" },
      { id: "accounting", label: "Accounting", icon: Landmark, perm: "cashbook.view" },
      { id: "reports", label: "Reports", icon: BarChart3, perm: ["reports.export", "rentals.view", "repairs.view", "parties.view", "portal.manage", "inventory.edit"] },
      { id: "broadcast", label: "Broadcast", icon: Megaphone, perm: "broadcast.send" },
    ],
  },
  {
    label: "Admin",
    items: [
      { id: "settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

function visibleNavGroups(me) {
  if (!me) return [];
  const perms = me.permissions || [];
  // `perm` can be a single codename or an array -- an array means "show
  // this item if the user holds ANY one of these", for a nav entry like
  // Reports that gates several sub-views each needing a different
  // permission (see Reports.jsx, which does its own per-tab check with
  // the same permissions once the user is inside the page).
  const holds = (code) => me.is_superuser || perms.includes(code);
  const allowed = (item) => {
    if (!item.perm) return true;
    return Array.isArray(item.perm) ? item.perm.some(holds) : holds(item.perm);
  };
  return NAV_GROUPS
    .map((group) => ({ ...group, items: group.items.filter(allowed) }))
    .filter((group) => group.items.length > 0);
}

function VersionBadge({ size = "xs" }) {
  return (
    <span
      className={size === "xs" ? "text-[10px]" : "text-xs"}
      style={{
        fontFamily: F.mono, fontWeight: 700, color: C.orange,
        border: `1.5px solid ${C.orange}`, padding: "1px 6px",
        letterSpacing: "0.05em", backgroundColor: `${C.orange}14`,
      }}
    >
      {APP_VERSION}
    </span>
  );
}

function Shell() {
  const { me, logout } = useSession();
  const [view, setView] = useState("home");
  const groups = visibleNavGroups(me);
  const flatNav = groups.flatMap((g) => g.items);

  return (
    <div className="cb-shell flex h-screen w-full overflow-hidden">
      <div className="fixed inset-x-0 top-0 z-10 md:hidden" style={{ backgroundColor: C.deep, borderBottom: `1px solid ${C.sidebarHover}` }}>
        <div className="flex items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2">
            <span style={{ fontFamily: F.display, fontWeight: 700, color: "#FFFFFF", letterSpacing: "0.02em" }}>{APP_NAME}</span>
            <span className="text-[10px]" style={{ fontFamily: F.mono, fontWeight: 700, color: C.sidebarActiveText, border: `1.5px solid ${C.sidebarActive}`, padding: "1px 6px", letterSpacing: "0.05em", backgroundColor: C.sidebarActive }}>{APP_VERSION}</span>
          </span>
          <button onClick={logout}><LogOut size={16} style={{ color: C.sidebarText }} /></button>
        </div>
        <div className="flex gap-4 overflow-x-auto px-4 pb-2">
          {flatNav.map(({ icon: Icon, label, id }) => (
            <button key={id} onClick={() => setView(id)} className="flex shrink-0 items-center gap-1.5 pb-1 text-xs" style={{ fontFamily: F.body, fontWeight: view === id ? 600 : 400, color: view === id ? "#FFFFFF" : C.sidebarText, borderBottom: `2px solid ${view === id ? C.sidebarActive : "transparent"}` }}>
              <Icon size={14} />{label}
            </button>
          ))}
        </div>
      </div>

      <aside className="hidden w-64 shrink-0 flex-col py-6 md:flex" style={{ backgroundColor: C.deep }}>
        {/* Nav scrolls independently and never pushes the account block
            below the fold -- min-h-0 is required for a flex child to be
            allowed to shrink/scroll instead of overflowing its parent. */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="px-5">
            {/* Decorative only -- echoes the reference screenshot's window
                chrome (macOS traffic lights). Purely cosmetic, no window
                controls are wired to these. */}
            <div className="mb-3 flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#EA5F57" }} />
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#F6BE4F" }} />
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#61C454" }} />
            </div>
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full" style={{ backgroundColor: C.sidebarActive }}>
                <span style={{ fontFamily: F.display, fontWeight: 800, color: "#FFFFFF", fontSize: 13 }}>V</span>
              </span>
              <p className="text-lg" style={{ fontFamily: F.display, fontWeight: 800, color: "#FFFFFF", letterSpacing: "-0.01em" }}>{APP_NAME}</p>
              <span className="text-[10px]" style={{ fontFamily: F.mono, fontWeight: 700, color: C.sidebarActiveText, border: `1.5px solid ${C.sidebarActive}`, padding: "1px 6px", letterSpacing: "0.05em", backgroundColor: `${C.sidebarActive}55` }}>{APP_VERSION}</span>
            </div>
            
          </div>
          <nav className="mt-8 space-y-5 px-3">
            {groups.map((group) => (
              <div key={group.label}>
                <p className="px-2 pb-1.5 text-[10px] uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.16em", color: C.sidebarTextDim }}>{group.label}</p>
                <div className="space-y-0.5">
                  {group.items.map(({ icon: Icon, label, id }) => {
                    const active = view === id;
                    return (
                      <button
                        key={id}
                        onClick={() => setView(id)}
                        className="flex w-full items-center gap-2.5 px-3 py-2 text-sm"
                        style={{
                          fontFamily: F.body, fontWeight: active ? 700 : 500, borderRadius: 999,
                          color: active ? C.sidebarActiveText : C.sidebarText,
                          backgroundColor: active ? C.sidebarActive : "transparent",
                        }}
                      >
                        <Icon size={15} /><span className="flex-1 text-left">{label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </div>
        {/* Signed-in user, role, and sign-out now live in the shared header
            (top right, via PageHeader's avatar) instead of down here --
            keeps the sidebar to navigation only. */}
      </aside>

      <main className="mt-24 flex min-w-0 flex-1 flex-col overflow-hidden md:mt-0">
        {view === "home" && <Dashboard onGo={setView} />}
        {view === "inventory" && <Inventory />}
        {view === "invoices" && <Invoices />}
        {view === "parties" && <Parties />}
        {view === "rentals" && <Rentals />}
        {view === "accounting" && <Accounting />}
        {view === "reports" && <Reports />}
        {view === "repairs" && <Repairs />}
        {view === "warranty" && <Warranty />}
        {view === "broadcast" && <Broadcast />}
        {view === "settings" && <Settings />}
      </main>
    </div>
  );
}

function Gate() {
  const { me, loading } = useSession();
  if (loading) return <div className="cb-shell flex h-screen items-center justify-center"><Spinner label="Checking session…" /></div>;
  return me ? <Shell /> : <Login />;
}

export default function App() {
  const repairOrderMatch = window.location.pathname.match(/^\/repair-order-approval\/([^/]+)\/?$/);
  if (repairOrderMatch) {
    return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label="Loading secure approval…" /></div>}>{(
      <>
        <AnimatedGradientBackground />
        <RepairOrderApproval token={decodeURIComponent(repairOrderMatch[1])} />
      </>
    )}</Suspense>;
  }
  const portalMatch = window.location.pathname.match(/^\/portal(?:\/([^/]+))?\/?$/);
  if (portalMatch) {
    return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label="Loading your portal…" /></div>}>{(
      <PortalApp token={portalMatch[1] ? decodeURIComponent(portalMatch[1]) : null} />
    )}</Suspense>;
  }
  const rentalMatch = window.location.pathname.match(/^\/rental-approval\/([^/]+)\/?$/);
  if (rentalMatch) {
    return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label="Loading secure approval…" /></div>}>{(
      <>
        <AnimatedGradientBackground />
        <RentalApproval token={decodeURIComponent(rentalMatch[1])} />
      </>
    )}</Suspense>;
  }
  const match = window.location.pathname.match(/^\/repair-approval\/([^/]+)\/?$/);
  if (match) {
    return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label="Loading secure approval…" /></div>}>{(
      <>
        <AnimatedGradientBackground />
        <RepairApproval token={decodeURIComponent(match[1])} />
      </>
    )}</Suspense>;
  }
  return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label={`Loading ${APP_NAME}…`} /></div>}>{(
    <SessionProvider>
      <AnimatedGradientBackground />
      <Gate />
    </SessionProvider>
  )}</Suspense>;
}
