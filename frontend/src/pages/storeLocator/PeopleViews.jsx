import { useMemo, useState } from "react";
import { ArrowRight, ChevronDown, Globe, History, KeyRound, Network, PackageX, ShieldCheck, TrendingDown, UserX, Users, Warehouse } from "lucide-react";
import { SearchInput } from "../../components/Atoms";
import { Badge, Segmented, SelectPill, StateBox, StoreMark } from "./shared";
import { initials, isShop, num, oneLine, personName, plural } from "./format";

/*
 * Staff and Roles views of the Store & Channel Management page.
 *
 * Staff come from GET /users/ (store-scoped by the backend: the Owner sees
 * the whole team, store staff their own store's team). A staff member's
 * store is accounts.User.stock_point, set only by the Owner -- never
 * inferred from role, activity or logins. Roles come from GET /roles/.
 */

function StoreCell({ user }) {
  if (user.sees_all_stores) return <Badge tone="violet" icon={ShieldCheck}>All stores</Badge>;
  if (!user.stock_point) return <Badge tone="amber" icon={UserX}>Unassigned</Badge>;
  return <Badge tone="blue" title={user.stock_point_name}>{user.stock_point_name}</Badge>;
}

function Person({ user }) {
  const name = personName(user);
  return (
    <span className="sl-person">
      <span className="sl-avatar" aria-hidden="true">{initials(name)}</span>
      <span className="min-w-0">
        <span className="sl-row-name" title={name}>{name}</span>
        <span className="sl-row-sub" title={`@${user.username}`}>@{user.username}</span>
      </span>
    </span>
  );
}

// onOpenLogs: only passed for viewers allowed to read activity logs (me.can_view_staff_logs);
// each row's Logs button also needs the backend's per-account can_view_activity
export function StaffView({ users, points, counts, ownerView, onOpenStore, onOpenInventory, onOpenLogs }) {
  const [mode, setMode] = useState("map");
  const [store, setStore] = useState("all");
  const [q, setQ] = useState("");
  const shops = points.filter(isShop);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return users.filter((u) => {
      if (store === "unassigned" && (u.stock_point || u.sees_all_stores)) return false;
      if (store === "owner" && !u.sees_all_stores) return false;
      if (!["all", "unassigned", "owner"].includes(store) && String(u.stock_point) !== store) return false;
      if (!needle) return true;
      return [personName(u), u.username, u.role_label, u.stock_point_name].some((x) => (x || "").toLowerCase().includes(needle));
    }).sort((a, b) => personName(a).localeCompare(personName(b)));
  }, [users, store, q]);

  if (!users.length) {
    return <StateBox icon={Users} title="No staff accounts in your scope" text="Staff appear here once they have accounts — and, for store staff, a Store Location." />;
  }

  const unassigned = users.filter((u) => !u.stock_point && !u.sees_all_stores);
  const owners = users.filter((u) => u.sees_all_stores);

  return (
    <div className="sl-stack">
      <div className="sl-tools">
        <Segmented label="Staff view" value={mode} onChange={setMode}
          options={[{ id: "map", label: "Store mapping" }, { id: "list", label: "Staff list", count: users.length }]} />
        {mode === "list" && (
          <>
            <SearchInput value={q} onChange={(e) => setQ(e.target.value)} onClear={() => setQ("")} placeholder="Search name, role or store" />
            {ownerView && (
              <SelectPill label="Store" value={store} onChange={setStore}>
                <option value="all">All staff</option>
                <option value="unassigned">Unassigned ({unassigned.length})</option>
                <option value="owner">All-store accounts ({owners.length})</option>
                {shops.map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
              </SelectPill>
            )}
          </>
        )}
      </div>

      {mode === "map" ? (
        <>
          <p className="sl-note">
            How each team member connects to a physical shop, that shop's stock and its operations. Assignments come only from each
            account's Store Location{ownerView ? ", which you set in Settings → Roles & access" : ""}.
          </p>
          <div className="sl-map">
            {shops.map((s) => {
              const team = users.filter((u) => u.stock_point === s.id);
              const c = counts?.[s.id];
              return (
                <section key={s.id} className="sl-lane" aria-label={`${s.name} mapping`}>
                  <header className="sl-lane-head">
                    <StoreMark sp={s} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="sl-row-name">{s.name}</p>
                      <p className="sl-row-sub sl-wrap">{s.address ? oneLine(s.address) : "Address not configured"}</p>
                    </div>
                  </header>
                  <div className="sl-lane-step">
                    <p className="sl-lane-label"><Users size={12} aria-hidden="true" />Staff · {team.length}</p>
                    {team.length ? (
                      <ul className="sl-chips">
                        {team.map((u) => (
                          <li key={u.id} className="sl-chip" data-inactive={!u.is_active} title={u.role_label || "No role"}>
                            <span className="sl-avatar" data-size="xs" aria-hidden="true">{initials(personName(u))}</span>
                            {personName(u)}
                          </li>
                        ))}
                      </ul>
                    ) : <p className="sl-note">No one is assigned here yet.</p>}
                  </div>
                  <div className="sl-lane-step">
                    <p className="sl-lane-label"><Warehouse size={12} aria-hidden="true" />Inventory</p>
                    {c ? (
                      <div className="sl-lane-stats">
                        <button type="button" onClick={() => onOpenInventory(s.id, "all")}><b>{num(c.product_units)}</b> units</button>
                        <button type="button" data-tone={c.low_stock ? "amber" : undefined} onClick={() => onOpenInventory(s.id, "low")}>
                          <TrendingDown size={12} aria-hidden="true" /><b>{num(c.low_stock)}</b> low
                        </button>
                        <button type="button" data-tone={c.out_of_stock ? "red" : undefined} onClick={() => onOpenInventory(s.id, "out")}>
                          <PackageX size={12} aria-hidden="true" /><b>{num(c.out_of_stock)}</b> out
                        </button>
                      </div>
                    ) : <p className="sl-note">Inventory totals unavailable.</p>}
                  </div>
                  <button type="button" className="sl-lane-foot" onClick={() => onOpenStore(s)}>
                    Operations &amp; details <ArrowRight size={13} aria-hidden="true" />
                  </button>
                </section>
              );
            })}
            {ownerView && (
              <section className="sl-lane" data-kind="pending" aria-label="Unassigned staff">
                <header className="sl-lane-head">
                  <span className="sl-mark" data-size="sm" data-kind="pending" aria-hidden="true"><UserX size={15} /></span>
                  <div className="min-w-0 flex-1">
                    <p className="sl-row-name">Unassigned</p>
                    <p className="sl-row-sub">No Store Location — these accounts see no store data</p>
                  </div>
                </header>
                <div className="sl-lane-step">
                  {unassigned.length ? (
                    <ul className="sl-chips">
                      {unassigned.map((u) => (
                        <li key={u.id} className="sl-chip" data-inactive={!u.is_active}>
                          <span className="sl-avatar" data-size="xs" aria-hidden="true">{initials(personName(u))}</span>{personName(u)}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="sl-note">Everyone has a Store Location.</p>}
                </div>
              </section>
            )}
          </div>
          {points.some((p) => !isShop(p)) && (
            <p className="sl-note"><Globe size={12} aria-hidden="true" className="inline align-[-2px]" /> Online channels are sales channels, not staff locations, so they have no lane here.</p>
          )}
        </>
      ) : filtered.length ? (
        <div className="sl-table" role="table" aria-label="Staff" data-logs={!!onOpenLogs}>
          <div className="sl-tr sl-th sl-tr-staff" role="row">
            <span role="columnheader">Name</span>
            <span role="columnheader">Role</span>
            <span role="columnheader">Store Location</span>
            <span role="columnheader">Status</span>
            {onOpenLogs && <span role="columnheader" className="sl-act">Actions</span>}
          </div>
          {filtered.map((u) => (
            <div key={u.id} className="sl-tr sl-tr-staff" role="row">
              <span role="cell" className="sl-td-main"><Person user={u} /></span>
              <span role="cell" data-label="Role"><span className="sl-cell-text" title={u.role_label || (u.is_superuser ? "Superuser" : "No role")}>{u.role_label || (u.is_superuser ? "Superuser" : "No role")}</span></span>
              <span role="cell" data-label="Store Location"><StoreCell user={u} /></span>
              <span role="cell" data-label="Status"><Badge tone={u.is_active ? "green" : "grey"}>{u.is_active ? "Active" : "Inactive"}</Badge></span>
              {onOpenLogs && (
                <span role="cell" className="sl-act">
                  {u.can_view_activity && (
                    <button type="button" className="sl-logs-btn" onClick={() => onOpenLogs(u)} aria-haspopup="dialog"
                      aria-label={`Activity logs for ${personName(u)}`} title={`View activity logs for ${personName(u)}`}>
                      <History size={13} aria-hidden="true" />Logs
                    </button>
                  )}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <StateBox compact icon={Users} title="No staff match" text="Change the search or the store filter." />
      )}
    </div>
  );
}

export function RolesView({ roles, users, ownerView }) {
  const [open, setOpen] = useState(null);
  if (!roles.length) {
    return <StateBox icon={KeyRound} title="No roles are defined" text="Roles are created in Settings → Roles & access." />;
  }
  const holders = (role) => users.filter((u) => u.role === role.id).length;
  return (
    <div className="sl-stack">
      <p className="sl-note">
        Roles decide which modules and actions an account can use; Store Location decides which store's records it reaches. Both apply.
        {!ownerView && " Staff counts cover your store's team only."} Roles are managed in Settings → Roles &amp; access.
      </p>
      <ul className="sl-roles">
        {roles.map((r) => {
          const expanded = open === r.id;
          return (
            <li key={r.id} className="sl-role" data-open={expanded}>
              <button type="button" className="sl-role-head" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : r.id)}>
                <span className="sl-mark" data-size="sm" data-kind={r.slug === "owner" ? "online" : "shop"} aria-hidden="true"><KeyRound size={15} /></span>
                <span className="min-w-0 flex-1">
                  <span className="sl-row-name">{r.label}</span>
                  <span className="sl-row-sub">{r.slug}</span>
                </span>
                {r.slug === "owner" && <Badge tone="violet" icon={Network}>All stores</Badge>}
                <span className="sl-role-stat">{plural(r.permission_codes.length, "permission")}</span>
                <span className="sl-role-stat">{plural(holders(r), "member")}</span>
                <ChevronDown size={16} aria-hidden="true" className="sl-role-caret" />
              </button>
              {expanded && (
                <div className="sl-role-body">
                  {r.permissions.length ? (
                    <ul className="sl-perm-list">
                      {r.permissions.map((p) => (
                        <li key={p.codename}><span className="sl-mono">{p.codename}</span><span>{p.description}</span></li>
                      ))}
                    </ul>
                  ) : <p className="sl-note">This role holds no permissions.</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="sl-note">{plural(roles.length, "role record")} in the role table — counted as roles, not as permissions.</p>
    </div>
  );
}
