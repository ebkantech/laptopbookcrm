import { useEffect, useState } from "react";
import {
  BadgeCheck, Check, LogOut, Mail, Minus, Phone, ShieldCheck, User as UserIcon,
} from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Locked, Pill, Spinner } from "../components/Atoms";

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

        <button onClick={logout} className="mt-5 flex items-center gap-1.5 px-3 py-2 text-xs uppercase" style={{ border: `1px solid ${C.carbon}`, color: C.carbon, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em" }}>
          <LogOut size={13} /> Sign out
        </button>
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

function RolesAccess() {
  const { can } = useSession();
  const [roles, setRoles] = useState(null);
  const [users, setUsers] = useState([]);

  useEffect(() => {
    api.get("/roles/").then((d) => setRoles(d.results ?? d));
    api.get("/users/").then((d) => setUsers(d.results ?? d));
  }, []);
  if (!can("roles.manage")) return <Locked label="Only the owner can view and change role access." />;
  if (!roles) return <Spinner />;

  const allPerms = [...new Map(roles.flatMap((r) => r.permissions).map((p) => [p.codename, p])).values()].sort((a, b) => a.codename.localeCompare(b.codename));

  return (
    <div>
      <Eyebrow>Object-based role access</Eyebrow>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Every action in accounting, sales, and inventory is a named permission below — a role is just the set it's allowed to touch.</p>
      <div className="mt-4 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>
            <th className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>Permission</th>
            {roles.map((r) => <th key={r.id} className="px-3 py-2 text-center text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{r.label}</th>)}
          </tr></thead>
          <tbody>
            {allPerms.map((p) => (
              <tr key={p.codename}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{p.description}</td>
                {roles.map((r) => (
                  <td key={r.id} className="px-3 py-2 text-center" style={{ borderBottom: `1px solid ${C.rule}` }}>
                    {r.permission_codes.includes(p.codename) ? <Check size={13} style={{ color: C.green, display: "inline" }} /> : <Minus size={13} style={{ color: C.rule, display: "inline" }} />}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Eyebrow>Team</Eyebrow>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {users.map((u) => (
          <div key={u.id} data-panel className="flex items-center justify-between px-3 py-2.5" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
            <span className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, color: C.ink }}><BadgeCheck size={14} style={{ color: C.stamp }} />{u.first_name} {u.last_name}</span>
            <Pill color={C.blue}>{u.role_label}</Pill>
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
  ];
  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 20, color: C.ink }}>Settings</p>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Your account, and who else can do what</p>
      <div className="mt-5 flex gap-4" style={{ borderBottom: `1px solid ${C.rule}` }}>
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className="flex items-center gap-1.5 pb-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: tab === t.id ? C.ink : C.inkSoft, borderBottom: `2px solid ${tab === t.id ? C.orange : "transparent"}` }}>
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>
      <div className="mt-5">
        {tab === "profile" && <Profile />}
        {tab === "roles" && <RolesAccess />}
      </div>
    </div>
  );
}
