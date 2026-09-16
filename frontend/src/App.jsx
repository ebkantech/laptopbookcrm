import { lazy, Suspense, useState } from "react";
import {
  LayoutDashboard, Package, Receipt, Users, Repeat2, Landmark, Megaphone,
  Wrench, ShieldCheck, LogOut, Bell, Settings as SettingsIcon, BadgeCheck,
} from "lucide-react";
import { C, F } from "./lib/theme";
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
const RepairApproval = lazy(() => import("./pages/RepairApproval"));
const RentalApproval = lazy(() => import("./pages/RentalApproval"));
const RepairOrderApproval = lazy(() => import("./pages/RepairOrderApproval"));

const NAV = [
  { id: "home", label: "Dashboard", icon: LayoutDashboard },
  { id: "inventory", label: "Inventory", icon: Package },
  { id: "invoices", label: "Sales & Invoices", icon: Receipt },
  { id: "parties", label: "Parties", icon: Users },
  { id: "rentals", label: "Rentals", icon: Repeat2 },
  { id: "accounting", label: "Accounting", icon: Landmark },
  { id: "repairs", label: "Repairs & Service", icon: Wrench },
  { id: "warranty", label: "Warranty", icon: BadgeCheck },
  { id: "broadcast", label: "Broadcast", icon: Megaphone },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

function Shell() {
  const { me, logout } = useSession();
  const [view, setView] = useState("home");

  return (
    <div className="cb-shell flex h-screen w-full overflow-hidden">
      <div className="fixed inset-x-0 top-0 z-10 md:hidden" style={{ backgroundColor: C.deep, borderBottom: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between px-4 py-3">
          <span style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>CRMBook</span>
          <button onClick={logout}><LogOut size={16} style={{ color: C.carbon }} /></button>
        </div>
        <div className="flex gap-4 overflow-x-auto px-4 pb-2">
          {NAV.map(({ icon: Icon, label, id }) => (
            <button key={id} onClick={() => setView(id)} className="flex shrink-0 items-center gap-1.5 pb-1 text-xs" style={{ fontFamily: F.body, fontWeight: view === id ? 600 : 400, color: view === id ? C.ink : C.inkSoft, borderBottom: `2px solid ${view === id ? C.orange : "transparent"}` }}>
              <Icon size={14} />{label}
            </button>
          ))}
        </div>
      </div>

      <aside className="hidden w-56 shrink-0 flex-col justify-between py-6 md:flex" style={{ backgroundColor: C.deep, borderRight: `1px solid ${C.rule}` }}>
        <div>
          <div className="px-5">
            <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.18em", color: C.orange }}>CRMBook</p>
            <p className="mt-2 text-base" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>Vantage Computers</p>
          </div>
          <nav className="mt-8">
            {NAV.map(({ icon: Icon, label, id }) => {
              const active = view === id;
              return (
                <button key={id} onClick={() => setView(id)} className="flex w-full items-center gap-2.5 px-5 py-2.5 text-sm" style={{ fontFamily: F.body, color: active ? C.ink : C.inkSoft, fontWeight: active ? 600 : 400, borderLeft: `2px solid ${active ? C.orange : "transparent"}` }}>
                  <Icon size={15} /><span className="flex-1 text-left">{label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="px-5">
          <div className="mb-3 flex items-center gap-2">
            <Bell size={13} style={{ color: C.carbon }} />
            <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Signed in</span>
          </div>
          <div className="flex items-start gap-2">
            <ShieldCheck size={14} className="mt-0.5 shrink-0" style={{ color: C.stamp }} />
            <span className="min-w-0">
              <span className="block truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{me.first_name} {me.last_name}</span>
              <span className="block text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{me.role_label || "Superuser"}</span>
            </span>
          </div>
          <button onClick={logout} className="mt-3 flex items-center gap-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            <LogOut size={13} /> Sign out
          </button>
        </div>
      </aside>

      <main className="mt-24 flex min-w-0 flex-1 flex-col overflow-hidden md:mt-0">
        {view === "home" && <Dashboard onGo={setView} />}
        {view === "inventory" && <Inventory />}
        {view === "invoices" && <Invoices />}
        {view === "parties" && <Parties />}
        {view === "rentals" && <Rentals />}
        {view === "accounting" && <Accounting />}
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
  return <Suspense fallback={<div className="cb-shell flex min-h-screen items-center justify-center"><Spinner label="Loading CRMBook…" /></div>}>{(
    <SessionProvider>
      <AnimatedGradientBackground />
      <Gate />
    </SessionProvider>
  )}</Suspense>;
}
