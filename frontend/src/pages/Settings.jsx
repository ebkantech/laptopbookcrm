import { useEffect, useState } from "react";
import {
  BadgeCheck, BellRing, Check, LogOut, Mail, Minus, Phone, Plus, ShieldCheck, User as UserIcon,
} from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Locked, Pill, PillButton, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";

function Profile() {
  const { me, logout } = useSession();
  if (!me) return <Spinner />;

  return (
    <div>
      <div data-panel className="p-5" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center" style={{ borderRadius: 999, backgroundColor: `${C.stamp}17`, border: `1px solid ${C.stamp}` }}>
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
          <div className="flex items-center gap-2 px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
            <Mail size={13} style={{ color: C.inkSoft }} />
            <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{me.email || "No email on file"}</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
            <Phone size={13} style={{ color: C.inkSoft }} />
            <span className="text-sm" style={{ fontFamily: F.body, color: C.ink }}>{me.phone || "No phone on file"}</span>
          </div>
        </div>

        <div className="mt-5">
          <PillButton icon={LogOut} onClick={logout}>Sign out</PillButton>
        </div>
      </div>

      <Eyebrow>Your permissions</Eyebrow>
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

function RolesAccess() {
  const { can, me } = useSession();
  const [roles, setRoles] = useState(null);
  const [users, setUsers] = useState([]);
  const [savingId, setSavingId] = useState(null);
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

  const loadRoles = () => api.get("/roles/").then((d) => setRoles(d.results ?? d));
  const loadUsers = () => api.get("/users/").then((d) => setUsers(d.results ?? d));

  useEffect(() => {
    loadRoles();
    loadUsers();
  }, []);
  if (!can("roles.manage")) return <Locked label="Only the owner can view and change role access." />;
  if (!roles) return <Spinner />;

  // The Owner role is tied to the superuser flag, not assignable here --
  // see accounts.views.UserViewSet.set_role.
  const assignableRoles = roles.filter((r) => r.slug !== "owner");

  const changeRole = async (user, roleSlug) => {
    if (roleSlug === user.role_slug) return;
    setError("");
    setSavingId(user.id);
    try {
      await api.post(`/users/${user.id}/set-role/`, { role: roleSlug });
      await loadUsers();
    } catch (e) {
      setError(e.body?.detail || e.message || "Couldn't change that user's role.");
    } finally {
      setSavingId(null);
    }
  };

  const allPerms = [...new Map(roles.flatMap((r) => r.permissions).map((p) => [p.codename, p])).values()].sort((a, b) => a.codename.localeCompare(b.codename));

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
      await Promise.all([loadRoles(), loadUsers()]);
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
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Every action in accounting, sales, and inventory is a named permission below — a role is just the set it's allowed to touch.</p>
      {error && <div className="mt-2"><ErrorNote message={error} /></div>}
      <div className="mt-4 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>
            <th className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>Permission</th>
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
            {allPerms.map((p) => (
              <tr key={p.codename}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{p.description}</td>
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
                          className="inline-flex h-5 w-5 items-center justify-center disabled:opacity-50"
                          style={{ borderRadius: 4, border: `1px solid ${has ? C.green : C.rule}`, backgroundColor: has ? `${C.green}18` : "transparent" }}
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
                style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, backgroundColor: "#fff" }}
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
                      className="px-2.5 py-1 text-xs"
                      style={{ fontFamily: F.body, fontWeight: 600, border: `1px solid ${checked ? C.green : C.rule}`, color: checked ? C.green : C.inkSoft, backgroundColor: checked ? `${C.green}12` : "transparent" }}
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

      <Eyebrow>Team</Eyebrow>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Assign a role to change what someone can access -- takes effect on their next request, no re-login needed.</p>
      {error && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.carbon }}>{error}</p>}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {users.map((u) => (
          <div key={u.id} data-panel className="flex items-center justify-between px-3 py-2.5" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
            <span className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, color: C.ink }}><BadgeCheck size={14} style={{ color: C.stamp }} />{u.first_name} {u.last_name}</span>
            {u.is_superuser ? (
              <Pill color={C.blue}>Superuser</Pill>
            ) : (
              <select
                value={u.role_slug || ""}
                disabled={savingId === u.id || u.id === me.id}
                onChange={(e) => changeRole(u, e.target.value)}
                className="bg-transparent px-2 py-1 text-xs outline-none"
                style={{ fontFamily: F.body, fontWeight: 600, color: C.ink, border: `1px solid ${C.rule}` }}
              >
                {assignableRoles.map((r) => <option key={r.slug} value={r.slug}>{r.label}</option>)}
              </select>
            )}
          </div>
        ))}
      </div>
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
      api.get("/roles/").then((d) => d.results ?? d),
      api.get("/notification-rules/").then((d) => d.results ?? d),
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
                  <div key={r.id} className="flex items-center justify-between px-3 py-2" style={{ backgroundColor: C.slip2 }}>
                    <span className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{r.label}</span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_inapp`}
                        onClick={() => toggle(ev.key, r, "via_inapp")}
                        className="flex items-center px-2 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${inappOn ? C.green : C.rule}`, color: inappOn ? C.green : C.inkSoft, backgroundColor: inappOn ? `${C.green}14` : "transparent" }}
                      >
                        <BellRing size={10} style={{ marginRight: 3 }} />Bell
                      </button>
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_email`}
                        onClick={() => toggle(ev.key, r, "via_email")}
                        className="flex items-center px-2 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${emailOn ? C.green : C.rule}`, color: emailOn ? C.green : C.inkSoft, backgroundColor: emailOn ? `${C.green}14` : "transparent" }}
                      >
                        <Mail size={10} style={{ marginRight: 3 }} />Email
                      </button>
                      <button
                        type="button"
                        disabled={busyKey === `${ev.key}:${r.id}:via_whatsapp`}
                        onClick={() => toggle(ev.key, r, "via_whatsapp")}
                        className="flex items-center px-2 py-1 text-[10px] disabled:opacity-50"
                        style={{ fontFamily: F.body, fontWeight: 700, border: `1px solid ${waOn ? C.green : C.rule}`, color: waOn ? C.green : C.inkSoft, backgroundColor: waOn ? `${C.green}14` : "transparent" }}
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
  const [tab, setTab] = useState("profile");
  const tabs = [
    { id: "profile", label: "Profile", icon: UserIcon },
    { id: "roles", label: "Roles & access", icon: ShieldCheck },
    { id: "notifications", label: "Staff alerts", icon: BellRing },
  ];
  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <PageHeader title="Settings" subtitle="Your account, and who else can do what" />
      <div className="mt-5">
        <TabBar tabs={tabs} value={tab} onChange={setTab} />
      </div>
      <div className="mt-5">
        {tab === "profile" && <Profile />}
        {tab === "roles" && <RolesAccess />}
        {tab === "notifications" && <StaffNotifications />}
      </div>
    </div>
  );
}
