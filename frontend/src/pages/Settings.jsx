import SubscriptionPanel from "../components/SubscriptionPanel";
import { Fragment, useEffect, useState } from "react";
import {
  BellRing, Building2, Check, KeyRound, LogOut, Mail, Minus, Phone, Plus, ShieldCheck, User as UserIcon, Users, CreditCard } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Locked, Pill, PillButton, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import ChangePassword from "./settings/ChangePassword";
import StaffManagement from "./settings/StaffManagement";
import BusinessMessages from "./settings/BusinessMessages";
import { appEnabled, grantedCount, groupByApp, toggleAppCodes } from "./settings/appAccess";

function Profile() {
  const { me, logout } = useSession();
  if (!me) return <Spinner />;

  return (
    <div>
      <div data-panel className="p-5" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center" style={{ borderRadius: 999, backgroundColor: `color-mix(in srgb, ${C.stamp} 9%, transparent)`, border: `1px solid ${C.stamp}` }}>
            <UserIcon size={22} style={{ color: C.stamp }} />
          </div>
          <div className="min-w-0">
            <p className="text-lg" style={{ fontFamily: F.display, fontWeight: 700, color: C.ink }}>
              {me.first_name} {me.last_name}
            </p>
            <p className="mt-0.5 text-sm" style={{ fontFamily: F.mono, color: C.inkSoft }}>@{me.username}</p>
            <div className="mt-2">
              <Pill color={C.blue}><ShieldCheck size={11} />{me.is_superuser ? "Superuser" : me.role_label}</Pill>
            </div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex min-w-0 items-center gap-2 rounded-xl px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
            <Mail size={13} style={{ color: C.inkSoft }} />
            <span className="truncate text-sm" style={{ fontFamily: F.body, color: C.ink }}>{me.email || "No email on file"}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2 rounded-xl px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
            <Phone size={13} style={{ color: C.inkSoft }} />
            <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{me.phone || "No phone on file"}</span>
          </div>
        </div>

        <div className="mt-5">
          <PillButton icon={LogOut} onClick={logout}>Sign out</PillButton>
        </div>
      </div>

      <div className="mt-8"><Eyebrow>Your permissions</Eyebrow></div>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Everything your role grants you access to across the app.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {(me.permissions || []).length ? (
          me.permissions.map((p) => <Pill key={p} color={C.green}><Check size={11} />{p}</Pill>)
        ) : (
          <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No permissions assigned to your role yet.</p>
        )}
      </div>
    </div>
  );
}

function slugify(s) {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
}

function RolesAccess({ onManageStaff }) {
  const { can } = useSession();
  const [roles, setRoles] = useState(null);
  const [error, setError] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [togglingKey, setTogglingKey] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [showNewRole, setShowNewRole] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newPerms, setNewPerms] = useState([]);
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");

  const [apps, setApps] = useState(null);
  const [allPermissions, setAllPermissions] = useState([]);

  const loadRoles = () => api.getAll("/roles/").then(setRoles);

  useEffect(() => {
    loadRoles();
    api.get("/roles/apps/").then(setApps).catch(() => setApps([]));
    api.getAll("/permissions/").then(setAllPermissions).catch(() => {});
  }, []);
  if (!can("roles.manage")) return <Locked label="Your role can't view or change role access." />;
  if (!roles || !apps) return <Spinner />;

  const allPerms = [...new Map([...allPermissions, ...roles.flatMap((r) => r.permissions)].map((p) => [p.codename, p])).values()].sort((a, b) => a.codename.localeCompare(b.codename));
  const groups = groupByApp(apps, allPerms);

  const toggleApp = async (role, app) => {
    if (role.slug === "owner") return;
    const key = `${role.id}:app:${app.key}`;
    setError("");
    setTogglingKey(key);
    try {
      await api.patch(`/roles/${role.id}/`, { permission_codes: toggleAppCodes(role, app) });
      await loadRoles();
    } catch (e) {
      setError(e.body?.detail || e.message || "Couldn't update that app.");
    } finally {
      setTogglingKey(null);
    }
  };

  const togglePerm = async (role, codename) => {
    if (role.slug === "owner") return;
    const key = `${role.id}:${codename}`;
    setError("");
    setTogglingKey(key);
    const has = role.permission_codes.includes(codename);
    const nextCodes = has ? role.permission_codes.filter((c) => c !== codename) : [...role.permission_codes, codename];
    try {
      await api.patch(`/roles/${role.id}/`, { permission_codes: nextCodes });
      await loadRoles();
    } catch (e) {
      setError(e.body?.detail || e.message || "Couldn't update that permission.");
    } finally {
      setTogglingKey(null);
    }
  };

  const deleteRole = async (role) => {
    setError("");
    setDeletingId(role.id);
    try {
      await api.del(`/roles/${role.id}/`);
      setConfirmDeleteId(null);
      await loadRoles();
    } catch (e) {
      setError(e.body?.detail || e.message || "Couldn't delete that role.");
    } finally {
      setDeletingId(null);
    }
  };

  const createRole = async () => {
    setFormError("");
    if (!newLabel.trim()) {
      setFormError("Give the role a name.");
      return;
    }
    setCreating(true);
    try {
      await api.post("/roles/", { slug: slugify(newLabel), label: newLabel.trim(), permission_codes: newPerms });
      setNewLabel("");
      setNewPerms([]);
      setShowNewRole(false);
      await loadRoles();
    } catch (e) {
      setFormError(e.body?.detail || e.body?.slug?.[0] || e.body?.permission_codes?.[0] || e.message || "Couldn't create that role.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>Object-based role access</Eyebrow>
        <PillButton icon={ShieldCheck} onClick={() => { setEditMode((v) => !v); setConfirmDeleteId(null); setShowNewRole(false); }}>
          {editMode ? "Done editing" : "Edit roles"}
        </PillButton>
      </div>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Decide which apps each role can open, then fine-tune what they may do inside. Switch an app off and that role no longer sees it in the menu or reaches it at all. An Admin can only give access they hold themselves.</p>
      {error && <div className="mt-2"><ErrorNote message={error} /></div>}
      <div className="mt-4 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>
            <th className="sticky left-0 z-[1] px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}`, backgroundColor: C.slip }}>Permission</th>
            {roles.map((r) => (
              <th key={r.id} className="px-3 py-2 text-center text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>
                <div className="flex flex-col items-center gap-1">
                  <span>{r.label}</span>
                  {editMode && r.slug !== "owner" && (
                    confirmDeleteId === r.id ? (
                      <span className="flex items-center gap-1.5">
                        <button type="button" onClick={() => deleteRole(r)} disabled={deletingId === r.id} className="text-[10px]" style={{ fontFamily: F.body, fontWeight: 700, color: C.carbon }}>
                          {deletingId === r.id ? "…" : "Confirm"}
                        </button>
                        <button type="button" onClick={() => setConfirmDeleteId(null)} className="text-[10px]" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft }}>Cancel</button>
                      </span>
                    ) : (
                      <button type="button" onClick={() => setConfirmDeleteId(r.id)} className="text-[10px]" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft }}>Delete</button>
                    )
                  )}
                </div>
              </th>
            ))}
          </tr></thead>
          <tbody>
            {groups.map((app) => (
              <Fragment key={app.key}>
                <tr>
                  <td className="sticky left-0 z-[1] px-3 py-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.ink, backgroundColor: C.slip2, borderBottom: `1px solid ${C.rule}` }}>{app.label} <span style={{ fontWeight: 400, color: C.inkSoft }}>· app access</span></td>
                  {roles.map((r) => {
                    const on = appEnabled(r, app);
                    const key = `${r.id}:app:${app.key}`;
                    const editable = editMode && r.slug !== "owner" && !!app.view;
                    return (
                      <td key={r.id} className="px-3 py-2 text-center" style={{ backgroundColor: C.slip2, borderBottom: `1px solid ${C.rule}` }}>
                        {editable ? (
                          <button type="button" onClick={() => toggleApp(r, app)} disabled={togglingKey === key} role="switch" aria-checked={on} aria-label={`${on ? "Turn off" : "Turn on"} ${app.label} for ${r.label}`}
                            className="inline-flex h-5 w-9 items-center rounded-full px-0.5 disabled:opacity-50" style={{ backgroundColor: on ? C.green : C.rule, justifyContent: on ? "flex-end" : "flex-start" }}>
                            <span className="h-4 w-4 rounded-full" style={{ backgroundColor: "#fff" }} />
                          </button>
                        ) : (
                          <span className="text-[11px]" style={{ fontFamily: F.body, fontWeight: 700, color: on ? C.green : C.inkSoft }}>{on ? `On · ${grantedCount(r, app)}/${app.permissions.length}` : grantedCount(r, app) ? `Off · ${grantedCount(r, app)} left` : "Off"}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
                {app.perms.map((p) => (
                  <tr key={p.codename}>
                    <td className="sticky left-0 z-[1] min-w-[180px] px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}`, backgroundColor: C.slip }}>{p.description}</td>
                    {roles.map((r) => {
                      const has = r.permission_codes.includes(p.codename);
                      const editable = editMode && r.slug !== "owner";
                      const key = `${r.id}:${p.codename}`;
                      return (
                        <td key={r.id} className="px-3 py-2 text-center" style={{ borderBottom: `1px solid ${C.rule}` }}>
                          {editable ? (
                            <button
                              type="button"
                              onClick={() => togglePerm(r, p.codename)}
                              disabled={togglingKey === key}
                              aria-pressed={has}
                              aria-label={`${has ? "Remove" : "Grant"} ${p.codename} for ${r.label}`}
                              className="inline-flex h-6 w-6 items-center justify-center disabled:opacity-50"
                              style={{ borderRadius: 4, border: `1px solid ${has ? C.green : C.rule}`, backgroundColor: has ? `color-mix(in srgb, ${C.green} 9%, transparent)` : "transparent" }}
                            >
                              {has && <Check size={12} style={{ color: C.green }} />}
                            </button>
                          ) : (
                            has ? <Check size={13} style={{ color: C.green, display: "inline" }} /> : <Minus size={13} style={{ color: C.rule, display: "inline" }} />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {editMode && (
        <div className="mt-3">
          {!showNewRole ? (
            <PillButton icon={Plus} onClick={() => setShowNewRole(true)}>Add role</PillButton>
          ) : (
            <div data-panel className="p-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
              <Eyebrow>New role</Eyebrow>
              {formError && <div className="mt-2"><ErrorNote message={formError} /></div>}
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="Role name, e.g. Store Supervisor"
                className="mt-2 w-full max-w-xs px-3 py-2 text-sm outline-none"
                style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, backgroundColor: C.slip }}
              />
              <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>slug: {slugify(newLabel) || "—"}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {allPerms.map((p) => {
                  const checked = newPerms.includes(p.codename);
                  return (
                    <button
                      type="button"
                      key={p.codename}
                      onClick={() => setNewPerms((cur) => (checked ? cur.filter((c) => c !== p.codename) : [...cur, p.codename]))}
                      aria-pressed={checked}
                      className="rounded-full px-2.5 py-1 text-xs"
                      style={{ fontFamily: F.body, fontWeight: 600, border: `1px solid ${checked ? C.green : C.rule}`, color: checked ? C.green : C.inkSoft, backgroundColor: checked ? `color-mix(in srgb, ${C.green} 7%, transparent)` : "transparent" }}
                    >
                      {p.codename}
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <PillButton primary onClick={createRole} disabled={creating}>{creating ? "Creating…" : "Create role"}</PillButton>
                <PillButton onClick={() => { setShowNewRole(false); setNewLabel(""); setNewPerms([]); setFormError(""); }}>Cancel</PillButton>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mt-8"><Eyebrow>Team</Eyebrow></div>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
        Assigning roles and Store Locations to people, adding staff, resetting passwords and deactivating accounts now live under Staff management.
      </p>
      <div className="mt-3"><PillButton icon={Users} onClick={onManageStaff}>Open Staff management</PillButton></div>
    </div>
  );
}

function StaffNotifications() {
  const { can } = useSession();
  const [events, setEvents] = useState(null);
  const [roles, setRoles] = useState(null);
  const [rules, setRules] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([
      api.get("/notification-rules/events/"),
      api.getAll("/roles/"),
      api.getAll("/notification-rules/"),
    ]).then(([ev, rl, ru]) => {
      setEvents(ev);
      setRoles(rl);
      setRules(ru);
    });

  useEffect(() => {
    load();
  }, []);

  if (!can("roles.manage")) return <Locked label="Only the owner can view and change staff alerts." />;
  if (!events || !roles || !rules) return <Spinner />;

  const ruleFor = (eventKey, roleId) => rules.find((r) => r.event_key === eventKey && r.role === roleId);

  const toggle = async (eventKey, role, channel) => {
    const key = `${eventKey}:${role.id}:${channel}`;
    setError("");
    setBusyKey(key);
    const existing = ruleFor(eventKey, role.id);
    try {
      if (existing) {
        await api.patch(`/notification-rules/${existing.id}/`, { [channel]: !existing[channel] });
      } else {
        await api.post("/notification-rules/", {
          event_key: eventKey, role: role.id,
          via_email: channel === "via_email", via_whatsapp: channel === "via_whatsapp", via_inapp: channel === "via_inapp",
        });
      }
      const d = await api.get("/notification-rules/");
      setRules(d.results ?? d);
    } catch (e) {
      setError(e.body?.detail || e.message || "Couldn't update that alert.");
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div>
      <Eyebrow>Staff alerts</Eyebrow>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>
        Who on the team gets pinged — and how — when one of these happens. Separate from what customers are sent (see docs/NOTIFICATIONS.md); this is internal only. Bell shows up in the header's notification icon right away; Email and WhatsApp still use the simulated senders until a real provider is wired up.
      </p>
      {error && <div className="mt-2"><ErrorNote message={error} /></div>}
      <div className="mt-4 space-y-4">
        {events.map((ev) => (
          <div key={ev.key} data-panel className="p-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
            <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>{ev.label}</p>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {roles.map((r) => {
                const rule = ruleFor(ev.key, r.id);
                const emailOn = !!rule?.via_email;
                const waOn = !!rule?.via_whatsapp;
                const inappOn = !!rule?.via_inapp;
                return (
                  <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2" style={{ backgroundColor: C.slip2 }}>
                    <span className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.label}</span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_inapp`}
                        onClick={() => toggle(ev.key, r, "via_inapp")}
                        aria-pressed={inappOn}
                        className="flex items-center rounded-full px-2.5 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${inappOn ? C.green : C.rule}`, color: inappOn ? C.green : C.inkSoft, backgroundColor: inappOn ? `color-mix(in srgb, ${C.green} 8%, transparent)` : "transparent" }}
                      >
                        <BellRing size={10} style={{ marginRight: 3 }} />Bell
                      </button>
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_email`}
                        onClick={() => toggle(ev.key, r, "via_email")}
                        aria-pressed={emailOn}
                        className="flex items-center rounded-full px-2.5 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${emailOn ? C.green : C.rule}`, color: emailOn ? C.green : C.inkSoft, backgroundColor: emailOn ? `color-mix(in srgb, ${C.green} 8%, transparent)` : "transparent" }}
                      >
                        <Mail size={10} style={{ marginRight: 3 }} />Email
                      </button>
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_whatsapp`}
                        onClick={() => toggle(ev.key, r, "via_whatsapp")}
                        aria-pressed={waOn}
                        className="flex items-center rounded-full px-2.5 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${waOn ? C.green : C.rule}`, color: waOn ? C.green : C.inkSoft, backgroundColor: waOn ? `color-mix(in srgb, ${C.green} 8%, transparent)` : "transparent" }}
                      >
                        <Phone size={10} style={{ marginRight: 3 }} />WhatsApp
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Settings() {
  const { can, me } = useSession();
  const [picked, setTab] = useState(() => new URLSearchParams(window.location.search).get("tab") || "profile");
  // Staff see only their own account (profile + password). Everything about
  // other people and the business -- staff, roles, alerts, business details,
  // subscription -- is for staff administrators (roles.manage, the Owner, or
  // the Super Admin); the APIs behind those tabs enforce the same rule.
  const staffAdmin = !!me?.is_superuser || !!me?.sees_all_stores || can("roles.manage");
  const tabs = [
    { id: "profile", label: "Profile", icon: UserIcon },
    { id: "password", label: "My password", icon: KeyRound },
    ...(staffAdmin ? [
      { id: "staff", label: "Staff management", icon: Users },
      { id: "roles", label: "Roles & access", icon: ShieldCheck },
      { id: "notifications", label: "Staff alerts", icon: BellRing },
      { id: "business", label: "Business & messages", icon: Building2 },
      { id: "subscription", label: "Subscription", icon: CreditCard },
    ] : []),
  ];
  const tab = tabs.some((t) => t.id === picked) ? picked : "profile";
  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <PageHeader title="Settings" subtitle="Your account, and who else can do what" />
      <div className="mt-5">
        <TabBar tabs={tabs} value={tab} onChange={setTab} />
      </div>
      <div className="mt-5">
        {tab === "profile" && <Profile />}
        {tab === "password" && <ChangePassword />}
        {tab === "staff" && staffAdmin && <StaffManagement />}
        {tab === "roles" && <RolesAccess onManageStaff={() => setTab("staff")} />}
        {tab === "notifications" && <StaffNotifications />}
        {tab === "business" && <BusinessMessages />}
        {tab === "subscription" && staffAdmin && <SubscriptionPanel />}
      </div>
    </div>
  );
}
