import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Package,
  Receipt,
  Users,
  Repeat2,
  Landmark,
  Megaphone,
  Wrench,
  LogOut,
  Settings as SettingsIcon,
  BadgeCheck,
  BarChart3,
  ChevronRight,
  Menu,
  X,
  PanelLeftClose,
  PanelLeftOpen,
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
    items: [{ id: "home", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Manage",
    items: [
      {
        id: "inventory",
        label: "Inventory",
        icon: Package,
        perm: "inventory.edit",
      },
      {
        id: "invoices",
        label: "Sales & Invoices",
        icon: Receipt,
        perm: "invoices.view",
      },
      { id: "parties", label: "Parties", icon: Users, perm: "parties.view" },
      { id: "rentals", label: "Rentals", icon: Repeat2, perm: "rentals.view" },
      {
        id: "repairs",
        label: "Repairs & Service",
        icon: Wrench,
        perm: "repairs.view",
      },
      {
        id: "warranty",
        label: "Warranty",
        icon: BadgeCheck,
        perm: "warranty.manage",
      },
      {
        id: "accounting",
        label: "Accounting",
        icon: Landmark,
        perm: "cashbook.view",
      },
      {
        id: "reports",
        label: "Reports",
        icon: BarChart3,
        perm: [
          "reports.export",
          "rentals.view",
          "repairs.view",
          "parties.view",
          "portal.manage",
          "inventory.edit",
        ],
      },
      {
        id: "broadcast",
        label: "Broadcast",
        icon: Megaphone,
        perm: "broadcast.send",
      },
    ],
  },
  {
    label: "Admin",
    items: [{ id: "settings", label: "Settings", icon: SettingsIcon }],
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
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter(allowed),
  })).filter((group) => group.items.length > 0);
}

function VersionBadge({ size = "xs" }) {
  return (
    <span
      className={size === "xs" ? "text-[10px]" : "text-xs"}
      style={{
        fontFamily: F.mono,
        fontWeight: 700,
        color: C.orange,
        border: `1.5px solid ${C.orange}`,
        padding: "1px 6px",
        letterSpacing: "0.05em",
        backgroundColor: `${C.orange}14`,
      }}
    >
      {APP_VERSION}
    </span>
  );
}

function initials(me) {
  const a = (me?.first_name || "").trim()[0] || "";
  const b = (me?.last_name || "").trim()[0] || "";
  return (a + b).toUpperCase() || (me?.username || "?")[0].toUpperCase();
}

const readCollapsed = () => {
  try {
    return localStorage.getItem("cb_nav_collapsed") === "1";
  } catch {
    return false;
  }
};

const SIDEBAR_BG = "linear-gradient(180deg, #1C2434 0%, #151C2A 100%)";
// Keyboard focus ring comes from index.css (.cb-shell button:focus-visible).
const focusRing = "";

const ROUTE_VIEWS = {
  "/": "home", "/inventory": "inventory", "/sales": "invoices",
  "/invoices": "invoices", "/parties": "parties", "/rentals": "rentals",
  "/repairs": "repairs", "/warranty": "warranty", "/accounting": "accounting",
  "/reports": "reports", "/broadcast": "broadcast", "/settings": "settings",
};
const VIEW_ROUTES = { home: "/", inventory: "/inventory", invoices: "/sales", parties: "/parties", rentals: "/rentals", repairs: "/repairs", warranty: "/warranty", accounting: "/accounting", reports: "/reports", broadcast: "/broadcast", settings: "/settings" };
const routeView = () => {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (/^\/parties\/\d+$/.test(path)) return "parties";
  return ROUTE_VIEWS[path] || "home";
};

/* The nav itself -- shared by the desktop sidebar and the mobile drawer,
   so both always list exactly the same permission-filtered items. */
function NavGroups({ groups, view, onSelect, collapsed = false }) {
  return (
    <nav aria-label="Main navigation" className={collapsed ? "mt-6 space-y-3" : "mt-6 space-y-5"}>
      {groups.map((group) => (
        <div key={group.label}>
          {collapsed ? (
            <div className="mx-auto mb-2 h-px w-8" style={{ backgroundColor: "rgba(255,255,255,0.08)" }} />
          ) : (
            <div className="mb-2 flex items-center gap-2 px-3">
              <span className="h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: C.orange }} />
              <p className="text-[10px] font-extrabold uppercase tracking-[0.2em]" style={{ color: "#858D9B" }}>
                {group.label}
              </p>
              <div className="ml-auto h-px flex-1" style={{ backgroundColor: "rgba(255,255,255,0.07)" }} />
            </div>
          )}

          <div className="space-y-0.5">
            {group.items.map(({ icon: Icon, label, id }) => {
              const active = view === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onSelect(id)}
                  aria-current={active ? "page" : undefined}
                  title={collapsed ? label : undefined}
                  className={`group relative flex w-full items-center gap-3 overflow-hidden rounded-xl text-left transition-colors duration-150 ${focusRing} ${
                    collapsed ? "justify-center px-0 py-1" : "px-2 py-1"
                  } ${active ? "text-white" : "text-[#A5ACB9] hover:bg-white/[0.055] hover:text-white"}`}
                  // inline, not border-* classes: Bootstrap's .border utility
                  // is !important and would override them
                  style={{
                    border: `1px solid ${active ? `${C.orange}59` : "transparent"}`,
                    background: active ? `linear-gradient(100deg, ${C.orange}25, ${C.orange}09)` : undefined,
                  }}
                >
                  {active && (
                    <span
                      className="absolute bottom-2.5 left-0 top-2.5 w-[3px] rounded-r-full"
                      style={{ backgroundColor: C.orange, boxShadow: `0 0 12px ${C.orange}90` }}
                    />
                  )}
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                    style={{
                      color: active ? C.orange : "inherit",
                      backgroundColor: active ? `${C.orange}19` : "rgba(255,255,255,0.035)",
                    }}
                  >
                    <Icon size={17} strokeWidth={active ? 2.3 : 1.8} />
                  </span>
                  {!collapsed && (
                    <>
                      <span className="min-w-0 flex-1 text-[13px] leading-snug" style={{ fontWeight: active ? 700 : 500 }}>
                        {label}
                      </span>
                      {active && <ChevronRight size={14} strokeWidth={2.5} style={{ color: C.orange }} />}
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Brand({ collapsed = false }) {
  return (
    <div className={`flex min-w-0 items-center gap-3 ${collapsed ? "justify-center" : "px-1.5"}`}>
      <div
        className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-2xl"
        style={{ background: `linear-gradient(145deg, ${C.orange}, #2547B8)`, boxShadow: `0 6px 22px ${C.orange}30` }}
      >
        <span className="text-xl font-black" style={{ color: "#171A21", fontFamily: F.display }}>V</span>
        <div className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full" style={{ backgroundColor: "#FFF3D8" }} />
      </div>
      {!collapsed && (
        <div className="min-w-0 flex-1">
          <p className="truncate text-[16px] font-extrabold tracking-wide" style={{ color: "#F9FAFB", fontFamily: F.display }}>
            {APP_NAME}
          </p>
          <p className="mt-0.5 text-[9px] font-bold uppercase tracking-[0.2em]" style={{ color: "#9298A5" }}>
            Business control
          </p>
        </div>
      )}
    </div>
  );
}

/* Signed-in user + sign out. On desktop the only way to sign out used to
   be the Settings page; this puts it where people look for it. */
function UserCard({ me, onLogout, collapsed = false }) {
  if (!me) return null;
  const name = `${me.first_name || ""} ${me.last_name || ""}`.trim() || me.username;
  const role = me.role_label || (me.is_superuser ? "Owner" : "");
  const avatar = (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-xs font-bold"
      style={{ backgroundColor: `${C.orange}22`, color: C.orange, fontFamily: F.display }}
      title={collapsed ? `${name}${role ? ` — ${role}` : ""}` : undefined}
    >
      {initials(me)}
    </span>
  );
  const signOut = (
    <button
      type="button"
      onClick={onLogout}
      title="Sign out"
      aria-label="Sign out"
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-[#A5ACB9] transition-colors hover:bg-white/[0.07] hover:text-white ${focusRing}`}
    >
      <LogOut size={16} />
    </button>
  );

  if (collapsed) {
    return <div className="flex flex-col items-center gap-2">{avatar}{signOut}</div>;
  }
  return (
    <div
      className="flex items-center gap-2.5 rounded-2xl p-2.5"
      style={{ background: "linear-gradient(135deg, #232731, #191C23)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      {avatar}
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-bold text-white">{name}</p>
        {role && <p className="mt-0.5 truncate text-[10px]" style={{ color: "#9298A5" }}>{role}</p>}
      </div>
      {signOut}
    </div>
  );
}

function Shell() {
  const { me, logout } = useSession();
  const [view, setView] = useState(routeView);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toggleRef = useRef(null);
  const closeRef = useRef(null);
  const groups = visibleNavGroups(me);
  const current = groups.flatMap((g) => g.items).find((i) => i.id === view);

  const navigate = (id, { replace = false } = {}) => {
    const route = VIEW_ROUTES[id] || "/";
    const url = `${route}${window.location.search}${window.location.hash}`;
    window.history[replace ? "replaceState" : "pushState"]({ view: id }, "", url);
    setView(id);
  };

  useEffect(() => {
    const onPopState = () => setView(routeView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const allowed = groups.flatMap((group) => group.items).some((item) => item.id === view);
    if (!allowed) {
      window.history.replaceState({ view: "home" }, "", `/${window.location.search}${window.location.hash}`);
      setView("home");
    }
  }, [view, groups]);

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem("cb_nav_collapsed", next ? "1" : "0");
    } catch {
      // a per-browser convenience only -- the sidebar still works without it
    }
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    toggleRef.current?.focus();
  };

  const selectFromDrawer = (id) => {
    navigate(id);
    setDrawerOpen(false);
  };

  // While the drawer is open: focus its close button and let Escape close it.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") {
        setDrawerOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className="cb-shell flex h-screen w-full flex-col overflow-hidden lg:flex-row">
      {/* Mobile / tablet top bar -- in the normal flow (not fixed), so it
          can never sit on top of page content. */}
      <header
        className="flex h-14 shrink-0 items-center gap-2 px-2 sm:px-4 lg:hidden"
        style={{ background: SIDEBAR_BG, borderBottom: "1px solid rgba(255,255,255,0.08)" }}
      >
        <button
          ref={toggleRef}
          type="button"
          data-nav-toggle
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation menu"
          aria-expanded={drawerOpen}
          aria-controls="cb-nav-drawer"
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white hover:bg-white/10 ${focusRing}`}
        >
          <Menu size={20} />
        </button>
        <span className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-[15px] font-bold" style={{ fontFamily: F.display, color: "#FFFFFF" }}>{APP_NAME}</span>
          {current && (
            <>
              <span style={{ color: "#5D6472" }}>/</span>
              <span className="truncate text-sm" style={{ fontFamily: F.body, color: "#A5ACB9" }}>{current.label}</span>
            </>
          )}
        </span>
      </header>

      {/* Mobile / tablet navigation drawer */}
      <div className={`fixed inset-0 z-40 lg:hidden ${drawerOpen ? "" : "pointer-events-none"}`}>
        <div
          aria-hidden="true"
          className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${drawerOpen ? "opacity-100" : "opacity-0"}`}
          onClick={closeDrawer}
        />
        <aside
          id="cb-nav-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          aria-hidden={!drawerOpen}
          inert={!drawerOpen}
          className={`absolute inset-y-0 left-0 flex w-[288px] max-w-[85vw] flex-col shadow-2xl transition-transform duration-200 ${drawerOpen ? "translate-x-0" : "-translate-x-full"}`}
          style={{ background: SIDEBAR_BG, fontFamily: F.body }}
        >
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
            <div className="flex items-center justify-between gap-2">
              <Brand />
              <button
                ref={closeRef}
                type="button"
                onClick={closeDrawer}
                aria-label="Close navigation menu"
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[#A5ACB9] hover:bg-white/10 hover:text-white ${focusRing}`}
              >
                <X size={18} />
              </button>
            </div>
            <NavGroups groups={groups} view={view} onSelect={selectFromDrawer} />
            <div className="mt-auto pt-6">
              <UserCard me={me} onLogout={logout} />
            </div>
          </div>
        </aside>
      </div>

      {/* Desktop sidebar */}
      <aside
        className={`relative hidden shrink-0 flex-col overflow-hidden transition-[width] duration-200 lg:flex ${collapsed ? "w-[84px]" : "w-[260px]"}`}
        style={{ background: SIDEBAR_BG, borderRight: "1px solid rgba(255,255,255,0.08)", fontFamily: F.body }}
      >
        <div
          className="pointer-events-none absolute -left-20 top-16 h-48 w-48 rounded-full blur-[90px]"
          style={{ backgroundColor: `${C.orange}18` }}
        />
        <div className={`relative flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden py-5 ${collapsed ? "px-3" : "px-4"}`}>
          <Brand collapsed={collapsed} />
          <NavGroups groups={groups} view={view} onSelect={navigate} collapsed={collapsed} />
          <div className="mt-auto space-y-2 pt-6">
            <UserCard me={me} onLogout={logout} collapsed={collapsed} />
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className={`flex w-full items-center gap-2 rounded-xl py-2 text-[11px] font-semibold text-[#858D9B] transition-colors hover:bg-white/[0.055] hover:text-white ${focusRing} ${collapsed ? "justify-center" : "px-3"}`}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              {!collapsed && "Collapse sidebar"}
            </button>
          </div>
        </div>
      </aside>


<main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
  <Suspense
    fallback={
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Spinner label={`Loading ${current?.label || "module"}…`} />
      </div>
    }
  >
    {view === "home" && <Dashboard onGo={navigate} />}
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
  </Suspense>
</main>


    </div>
  );
}
function Gate() {
  const { me, loading } = useSession();
  if (loading)
    return (
      <div className="cb-shell flex h-screen items-center justify-center">
        <Spinner label="Checking session…" />
      </div>
    );
  return me ? <Shell /> : <Login />;
}

export default function App() {
  const repairOrderMatch = window.location.pathname.match(
    /^\/repair-order-approval\/([^/]+)\/?$/,
  );
  if (repairOrderMatch) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading secure approval…" />
          </div>
        }
      >
        {
          <>
            <AnimatedGradientBackground />
            <RepairOrderApproval
              token={decodeURIComponent(repairOrderMatch[1])}
            />
          </>
        }
      </Suspense>
    );
  }
  const portalMatch = window.location.pathname.match(
    /^\/portal(?:\/([^/]+))?\/?$/,
  );
  if (portalMatch) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading your portal…" />
          </div>
        }
      >
        {
          <PortalApp
            token={portalMatch[1] ? decodeURIComponent(portalMatch[1]) : null}
          />
        }
      </Suspense>
    );
  }
  const rentalMatch = window.location.pathname.match(
    /^\/rental-approval\/([^/]+)\/?$/,
  );
  if (rentalMatch) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading secure approval…" />
          </div>
        }
      >
        {
          <>
            <AnimatedGradientBackground />
            <RentalApproval token={decodeURIComponent(rentalMatch[1])} />
          </>
        }
      </Suspense>
    );
  }
  const match = window.location.pathname.match(
    /^\/repair-approval\/([^/]+)\/?$/,
  );
  if (match) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading secure approval…" />
          </div>
        }
      >
        {
          <>
            <AnimatedGradientBackground />
            <RepairApproval token={decodeURIComponent(match[1])} />
          </>
        }
      </Suspense>
    );
  }
  return (
    <Suspense
      fallback={
        <div className="cb-shell flex min-h-screen items-center justify-center">
          <Spinner label={`Loading ${APP_NAME}…`} />
        </div>
      }
    >
      {
        <SessionProvider>
          <AnimatedGradientBackground />
          <Gate />
        </SessionProvider>
      }
    </Suspense>
  );
}
