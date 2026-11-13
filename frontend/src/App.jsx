import SubscriptionBanner from "./components/SubscriptionBanner";
import Toaster from "./components/Toaster";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { MapPin } from "lucide-react";
import { C, F, APP_NAME } from "./lib/theme";
import { SessionProvider, useSession } from "./context/SessionContext";
import { MODULES, visibleModules } from "./lib/navConfig";
import { AppHeader, CommandPalette, ContextBar, MobileDrawer } from "./components/shell/AppHeader";
import CopilotPanel from "./components/CopilotPanel";
import { Spinner } from "./components/Atoms";
import AnimatedGradientBackground from "./components/AnimatedGradientBackground";
const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Inventory = lazy(() => import("./pages/Inventory"));
const StoreLocator = lazy(() => import("./pages/StoreLocator"));
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
const LeadApproval = lazy(() => import("./pages/LeadApproval"));
const Leads = lazy(() => import("./pages/Leads"));
const RepairOrderApproval = lazy(() => import("./pages/RepairOrderApproval"));
const SetPassword = lazy(() => import("./pages/SetPassword"));
const PortalApp = lazy(() => import("./PortalApp"));

// Which modules each account may open (and the menus that list them) is
// in lib/navConfig.js -- the same per-module permissions as before.

const ROUTE_VIEWS = {
  "/": "home", "/inventory": "inventory", "/sales": "invoices",
  "/invoices": "invoices", "/parties": "parties", "/rentals": "rentals", "/leads": "leads",
  "/repairs": "repairs", "/warranty": "warranty", "/accounting": "accounting",
  "/reports": "reports", "/broadcast": "broadcast", "/settings": "settings",
  "/store-locator": "storeLocator",
};
const VIEW_ROUTES = { home: "/", inventory: "/inventory", storeLocator: "/store-locator", invoices: "/sales", parties: "/parties", rentals: "/rentals", leads: "/leads", repairs: "/repairs", warranty: "/warranty", accounting: "/accounting", reports: "/reports", broadcast: "/broadcast", settings: "/settings" };
const routeView = () => {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (/^\/parties\/\d+$/.test(path)) return "parties";
  return ROUTE_VIEWS[path] || "home";
};

function Shell() {
  const { me, logout, contextVersion } = useSession();
  const [view, setView] = useState(routeView);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // bumped when a link carries its own ?tab= etc., so the page re-reads it
  const [visit, setVisit] = useState(0);
  const toggleRef = useRef(null);
  const closeRef = useRef(null);
  const allowedIds = visibleModules(me);
  const current = MODULES[view];

  const navigate = (id, { replace = false } = {}) => {
    const route = VIEW_ROUTES[id] || "/";
    const url = `${route}${window.location.search}${window.location.hash}`;
    window.history[replace ? "replaceState" : "pushState"]({ view: id }, "", url);
    setView(id);
  };

  // From the header, menus and palette: a module, optionally with its own
  // query string (a Settings tab, the Suppliers list) or a full path
  // (one customer's page -- opened the way Parties itself does it).
  const go = (id, search, path) => {
    if (path) {
      window.history.pushState({ view: id }, "", path);
      window.dispatchEvent(new PopStateEvent("popstate"));
      return;
    }
    if (search === undefined) return navigate(id);
    window.history.pushState({ view: id }, "", `${VIEW_ROUTES[id] || "/"}${search}`);
    setView(id);
    setVisit((n) => n + 1);
  };

  useEffect(() => {
    const onPopState = () => setView(routeView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (!allowedIds.includes(view)) {
      // land on the first app this role can open (always at least Settings)
      const first = allowedIds[0] || "settings";
      window.history.replaceState({ view: first }, "", `${VIEW_ROUTES[first] || "/"}${window.location.search}${window.location.hash}`);
      setView(first);
    }
  }, [view, allowedIds.join()]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ctrl/Cmd+K opens the command palette from anywhere.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const closeDrawer = (refocus = true) => {
    setDrawerOpen(false);
    if (refocus) toggleRef.current?.focus();
  };

  // While the drawer is open: focus its close button and let Escape close it.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") closeDrawer();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="cb-shell v2x-app flex h-[100dvh] w-full flex-col overflow-hidden">
      <AppHeader me={me} view={view} onGo={go} onLogout={logout} onOpenPalette={() => setPaletteOpen(true)}
        onOpenDrawer={() => setDrawerOpen(true)} drawerOpen={drawerOpen} toggleRef={toggleRef} />
      <ContextBar me={me} view={view} onGo={go} />
      <MobileDrawer me={me} view={view} open={drawerOpen} onClose={closeDrawer} onGo={go} onLogout={logout} closeRef={closeRef} />
      <CommandPalette me={me} open={paletteOpen} onClose={() => setPaletteOpen(false)} onGo={go} />

<main className="v2x-workspace-main relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
  <SubscriptionBanner />
  <Toaster />
  {/* Non-owner accounts only reach their own store's records
      (accounts.store_scope); until the Owner assigns one, every
      store-linked list comes back empty -- say why, everywhere. */}
  {me && !me.can_select_all_stores && !me.accessible_stores?.length && (me.staff_kind || "store") === "store" && (
    <div
      role="status"
      className="mx-[1rem] mt-3 flex items-start gap-2 rounded-xl px-3 py-2.5 text-xs sm:mx-[2rem]"
      style={{ fontFamily: F.body, fontWeight: 600, color: C.ink, backgroundColor: `color-mix(in srgb, ${C.amber} 8%, transparent)`, border: `1px solid color-mix(in srgb, ${C.amber} 33%, transparent)` }}
    >
      <MapPin size={14} style={{ color: C.amber, flexShrink: 0, marginTop: 1 }} />
      <span>Your Store Location has not been assigned yet. Please contact your administrator.</span>
    </div>
  )}
  {/* keyed by the active store / role: switching either remounts the open
      page, so it refetches everything under the new context */}
  <Suspense
    key={`${contextVersion}:${visit}`}
    fallback={
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Spinner label={`Loading ${current?.label || "module"}…`} />
      </div>
    }
  >
    {view === "home" && <Dashboard onGo={navigate} />}
    {view === "inventory" && <Inventory />}
    {view === "storeLocator" && <StoreLocator />}
    {view === "invoices" && <Invoices />}
    {view === "parties" && <Parties />}
    {view === "rentals" && <Rentals />}
    {view === "leads" && <Leads />}
    {view === "accounting" && <Accounting />}
    {view === "reports" && <Reports />}
    {view === "repairs" && <Repairs />}
    {view === "warranty" && <Warranty />}
    {view === "broadcast" && <Broadcast />}
    {view === "settings" && <Settings />}
  </Suspense>
</main>

  <CopilotPanel />
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
  // One-time password-setup link from an administrator (Settings > Staff
  // management). Public: the link itself is the credential.
  const setPasswordMatch = window.location.pathname.match(/^\/set-password\/([^/]+)\/([^/]+)\/?$/);
  if (setPasswordMatch) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading…" />
          </div>
        }
      >
        <AnimatedGradientBackground />
        <div className="cb-shell">
          <SetPassword uid={decodeURIComponent(setPasswordMatch[1])} token={decodeURIComponent(setPasswordMatch[2])} />
        </div>
      </Suspense>
    );
  }
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
  const leadMatch = window.location.pathname.match(/^\/lead-approval\/([^/]+)\/?$/);
  if (leadMatch) {
    return (
      <Suspense
        fallback={
          <div className="cb-shell flex min-h-screen items-center justify-center">
            <Spinner label="Loading secure approval…" />
          </div>
        }
      >
        <>
          <AnimatedGradientBackground />
          <LeadApproval token={decodeURIComponent(leadMatch[1])} />
        </>
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
