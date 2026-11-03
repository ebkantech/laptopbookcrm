import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Check, Copy, KeyRound, Link2, Mail, Pencil, Power, RefreshCw, ShieldCheck, Trash2, UserPlus, Users,
} from "lucide-react";
import { api } from "../../lib/api";
import { onStoreChanged } from "../../lib/storeEvents";
import { useSession } from "../../context/SessionContext";
import { SearchInput } from "../../components/Atoms";
import { apiErrors, initials, personName } from "./errors";
import { Alert, Dialog, PasswordInput, SelectInput, TextInput } from "./StaffUi";
import "./staff.css";

/*
 * Settings > Staff management. Everything goes through the existing
 * /users/ API, which enforces the rules (accounts.views.UserViewSet):
 *   - roles.manage holders (or the Owner) administer staff in their reach:
 *     the Owner everyone, a store administrator their own store's team;
 *   - no one can grant a role carrying permissions they don't hold;
 *   - Store Location changes and deletion are Owner-only;
 *   - accounts with history are deactivated, never deleted.
 * The UI mirrors those rules to avoid dead ends -- it is not the boundary.
 */

const PAGE_SIZE = 20;
const STATUS_TONE = { active: "green", inactive: "grey", pending: "amber" };

function roleCodes(role) { return new Set(role?.permission_codes || []); }

export default function StaffManagement() {
  const { me, refresh: refreshMe } = useSession();
  const ownerView = !!me?.sees_all_stores;
  const myCodes = useMemo(() => new Set(me?.permissions || []), [me]);
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState([]);
  const [shops, setShops] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [storeFilter, setStoreFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sort, setSort] = useState("name");
  const [page, setPage] = useState(0);
  const [dialog, setDialog] = useState(null); // { kind, user? }
  const [flash, setFlash] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [u, r, sp] = await Promise.all([api.getAll("/users/"), api.getAll("/roles/"), api.getAll("/stock-points/")]);
      setUsers(u);
      setRoles(r);
      setShops(sp.filter((s) => s.kind === "shop"));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  // a store was edited: staff rows and the Store Location picker show its name
  useEffect(() => onStoreChanged(() => load()), [load]);

  // Roles this administrator may hand out: never Owner, and (unless they're
  // the Owner) only roles whose permissions they hold themselves.
  const grantable = useMemo(() => roles.filter((r) => r.slug !== "owner" && (ownerView || [...roleCodes(r)].every((c) => myCodes.has(c)))), [roles, ownerView, myCodes]);

  const statusOf = (u) => (!u.is_active ? "inactive" : u.password_set === false ? "pending" : "active");
  const canManage = (u) => u.id !== me.id && !(u.is_superuser && !me.is_superuser) && !(u.sees_all_stores && !ownerView);

  const shown = useMemo(() => {
    if (!users) return [];
    const needle = q.trim().toLowerCase();
    const list = users.filter((u) => {
      if (roleFilter !== "all" && String(u.role ?? "none") !== roleFilter) return false;
      if (storeFilter === "unassigned" && (u.stock_point || u.sees_all_stores || (u.staff_kind || "store") !== "store")) return false;
      if (storeFilter === "owner" && !u.sees_all_stores) return false;
      if (!["all", "unassigned", "owner"].includes(storeFilter) && String(u.stock_point) !== storeFilter) return false;
      if (statusFilter !== "all" && statusOf(u) !== statusFilter) return false;
      if (!needle) return true;
      return [personName(u), u.username, u.email, u.role_label, u.stock_point_name].some((v) => (v || "").toLowerCase().includes(needle));
    });
    const by = {
      name: (a, b) => personName(a).localeCompare(personName(b)),
      role: (a, b) => (a.role_label || "~").localeCompare(b.role_label || "~") || personName(a).localeCompare(personName(b)),
      store: (a, b) => (a.stock_point_name || "~").localeCompare(b.stock_point_name || "~") || personName(a).localeCompare(personName(b)),
      recent: (a, b) => (b.last_login || "").localeCompare(a.last_login || ""),
    }[sort];
    return [...list].sort(by);
  }, [users, q, roleFilter, storeFilter, statusFilter, sort]); // eslint-disable-line react-hooks/exhaustive-deps

  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const pageRows = shown.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const counts = useMemo(() => {
    const c = { all: users?.length || 0, active: 0, inactive: 0, pending: 0, unassigned: 0 };
    (users || []).forEach((u) => {
      c[statusOf(u)] += 1;
      if (!u.stock_point && !u.sees_all_stores && (u.staff_kind || "store") === "store") c.unassigned += 1;
    });
    return c;
  }, [users]); // eslint-disable-line react-hooks/exhaustive-deps

  const done = (message) => {
    setDialog(null);
    setFlash(message);
    load();
    refreshMe?.();
  };

  const filterBy = (status) => { setStatusFilter(status); setStoreFilter("all"); setPage(0); };

  if (!me) return null; // the session is still loading

  return (
    <div className="st st-stack">
      <div className="st-head">
        <div className="min-w-0">
          <h2 className="st-title">Staff management</h2>
          <p className="st-desc">
            Add team members, set their role and Store Location, reset passwords and deactivate accounts.
            {ownerView ? " As the Owner you manage every store's team." : ` You manage the team at ${me.stock_point_name || "your store"}.`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="st-btn" onClick={load} disabled={loading}><RefreshCw size={14} aria-hidden="true" />Refresh</button>
          <button type="button" className="st-btn" data-variant="primary" onClick={() => setDialog({ kind: "add" })} disabled={!users}>
            <UserPlus size={15} aria-hidden="true" />Add staff
          </button>
        </div>
      </div>

      {flash && <Alert tone="ok">{flash}</Alert>}

      <div className="st-stats">
        {[["all", "Staff"], ["active", "Active"], ["pending", "Password not set"], ["inactive", "Inactive"]].map(([k, label]) => (
          <button key={k} type="button" className="st-stat" aria-pressed={statusFilter === k && storeFilter === "all"} onClick={() => filterBy(k)}>
            <b>{counts[k]}</b><span>{label}</span>
          </button>
        ))}
        {ownerView && (
          <button type="button" className="st-stat" aria-pressed={storeFilter === "unassigned"} onClick={() => { setStoreFilter("unassigned"); setStatusFilter("all"); setPage(0); }}>
            <b>{counts.unassigned}</b><span>No Store Location</span>
          </button>
        )}
      </div>

      <div className="st-tools">
        <SearchInput value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} onClear={() => setQ("")} placeholder="Search name, username, email, role or store" />
        <label className="st-select">Role
          <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(0); }}>
            <option value="all">All roles</option>
            {roles.map((r) => <option key={r.id} value={String(r.id)}>{r.label}</option>)}
            <option value="none">No role</option>
          </select>
        </label>
        {ownerView && (
          <label className="st-select">Store
            <select value={storeFilter} onChange={(e) => { setStoreFilter(e.target.value); setPage(0); }}>
              <option value="all">All stores</option>
              <option value="unassigned">Unassigned</option>
              <option value="owner">All-store accounts</option>
              {shops.map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
            </select>
          </label>
        )}
        <label className="st-select">Status
          <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}>
            <option value="all">Any status</option>
            <option value="active">Active</option>
            <option value="pending">Password not set</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <label className="st-select">Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="name">Name</option>
            <option value="role">Role</option>
            <option value="store">Store</option>
            <option value="recent">Last sign-in</option>
          </select>
        </label>
      </div>

      {error ? (
        <div className="st-state" role="alert">
          <AlertTriangle size={20} aria-hidden="true" style={{ color: "var(--cb-red)" }} />
          <p className="st-state-title">Couldn't load staff</p>
          <p className="st-note">{error.message}</p>
          <button type="button" className="st-btn" onClick={load}>Try again</button>
        </div>
      ) : !users ? (
        <div className="st-stack" aria-label="Loading staff">{[0, 1, 2, 3].map((i) => <span key={i} className="st-skel" style={{ height: 62 }} />)}</div>
      ) : !shown.length ? (
        <div className="st-state">
          <Users size={20} aria-hidden="true" />
          <p className="st-state-title">{users.length ? "No staff match these filters" : "No staff accounts yet"}</p>
          <p className="st-note">{users.length ? "Change the search or filters." : "Use Add staff to create the first account."}</p>
        </div>
      ) : (
        <>
          <div className="st-table" role="table" aria-label="Staff">
            <div className="st-tr st-th" role="row">
              <span role="columnheader">Staff member</span>
              <span role="columnheader">Role</span>
              <span role="columnheader">Store Location</span>
              <span role="columnheader">Status</span>
              <span role="columnheader" style={{ textAlign: "right" }}>Actions</span>
            </div>
            {pageRows.map((u) => {
              const status = statusOf(u);
              const manageable = canManage(u);
              return (
                <div key={u.id} className="st-tr" role="row" data-inactive={!u.is_active}>
                  <span role="cell" className="st-person">
                    <span className="st-avatar" aria-hidden="true">{initials(personName(u))}</span>
                    <span className="min-w-0">
                      <span className="st-name" title={personName(u)}>{personName(u)}{u.id === me.id && <span className="st-badge ml-1.5" data-tone="grey">You</span>}</span>
                      <span className="st-sub st-mono" title={`@${u.username}`}>@{u.username}</span>
                      {u.email && <span className="st-sub" title={u.email}>{u.email}</span>}
                    </span>
                  </span>
                  <span role="cell" data-label="Role" title={u.is_superuser ? "Superuser" : u.role_label || "No role"}>{u.is_superuser ? "Superuser" : u.role_label || <span className="st-sub">No role</span>}</span>
                  <span role="cell" data-label="Store Location">
                    {u.sees_all_stores ? <span className="st-badge" data-tone="violet"><ShieldCheck size={11} aria-hidden="true" />All stores</span>
                      : u.staff_kind === "outsourced" ? <span className="st-badge" data-tone="violet" title={u.company}>Outsourced{u.company ? ` · ${u.company}` : ""}</span>
                      : u.staff_kind === "field" ? <span className="st-badge" data-tone="blue">Field · any store</span>
                      : u.stock_point ? <span className="st-badge" title={u.stock_point_name}>{u.stock_point_name}</span>
                        : <span className="st-badge" data-tone="amber">Unassigned</span>}
                  </span>
                  <span role="cell" data-label="Status">
                    <span className="st-badge" data-tone={STATUS_TONE[status]}>{status === "pending" ? "Password not set" : status === "active" ? "Active" : "Inactive"}</span>
                  </span>
                  <span role="cell" className="st-actions">
                    {manageable ? (
                      <>
                        <button type="button" className="st-icon-btn" title="Edit" aria-label={`Edit ${personName(u)}`} onClick={() => setDialog({ kind: "edit", user: u })}><Pencil size={14} /></button>
                        <button type="button" className="st-icon-btn" title="Reset password" aria-label={`Reset password for ${personName(u)}`} disabled={!u.is_active} onClick={() => setDialog({ kind: "reset", user: u })}><KeyRound size={14} /></button>
                        <button type="button" className="st-icon-btn" title={u.is_active ? "Deactivate" : "Reactivate"} aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${personName(u)}`} onClick={() => setDialog({ kind: "active", user: u })}><Power size={14} /></button>
                        {ownerView && (
                          <button type="button" className="st-icon-btn" data-tone="danger" title="Delete staff" aria-label={`Delete ${personName(u)}`} onClick={() => setDialog({ kind: "delete", user: u })}><Trash2 size={14} /></button>
                        )}
                      </>
                    ) : (
                      <span className="st-note">{u.id === me.id ? "Use My password" : "Owner account"}</span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="st-pager">
            <p className="st-note" aria-live="polite">Showing {page * PAGE_SIZE + 1}–{Math.min(shown.length, (page + 1) * PAGE_SIZE)} of {shown.length}</p>
            {pages > 1 && (
              <div className="flex gap-2">
                <button type="button" className="st-btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button type="button" className="st-btn" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            )}
          </div>
        </>
      )}

      {dialog?.kind === "add" && (
        <StaffForm roles={grantable} shops={shops} ownerView={ownerView} me={me} onClose={() => setDialog(null)}
          onCreated={(user) => { load(); setDialog({ kind: "created", user }); }} />
      )}
      {dialog?.kind === "edit" && (
        <StaffForm user={dialog.user} roles={grantable} allRoles={roles} shops={shops} ownerView={ownerView} me={me}
          onClose={() => setDialog(null)} onSaved={(u) => done(`Saved changes to ${personName(u)}.`)} />
      )}
      {dialog?.kind === "created" && <CreatedDialog user={dialog.user} onClose={() => setDialog(null)} onSetup={() => setDialog({ kind: "reset", user: dialog.user, fresh: true })} />}
      {dialog?.kind === "reset" && <ResetDialog user={dialog.user} fresh={dialog.fresh} onClose={() => { setDialog(null); load(); }} />}
      {dialog?.kind === "active" && <ActiveDialog user={dialog.user} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === "delete" && (
        <DeleteDialog user={dialog.user} onClose={() => setDialog(null)} onDone={done}
          onDeactivate={() => setDialog({ kind: "active", user: dialog.user })} />
      )}
    </div>
  );
}

function StaffForm({ user, roles, allRoles, shops, ownerView, me, onClose, onCreated, onSaved }) {
  const editing = !!user;
  const [form, setForm] = useState({
    first_name: user?.first_name || "", last_name: user?.last_name || "", username: user?.username || "",
    email: user?.email || "", phone: user?.phone || "", role: user?.role ? String(user.role) : "",
    stock_point: user ? (user.stock_point ? String(user.stock_point) : "") : ownerView ? "" : String(me.stock_point || ""),
    is_active: user ? user.is_active : true, staff_kind: user?.staff_kind || "store", company: user?.company || "", mode: "link", password: "", password_confirm: "",
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => { setForm((f) => ({ ...f, [k]: v })); setErrors((e) => ({ ...e, [k]: undefined, _form: undefined })); };
  // keep the current role listed even if this administrator couldn't grant it
  const roleOptions = editing && user.role && !roles.some((r) => r.id === user.role)
    ? [...roles, ...(allRoles || []).filter((r) => r.id === user.role)] : roles;

  const submit = async (e) => {
    e.preventDefault();
    const local = {};
    if (!form.first_name.trim()) local.first_name = "Enter a first name.";
    if (!form.username.trim()) local.username = "Choose a username.";
    if (!editing && form.mode === "set") {
      if (form.password.length < 10) local.password = "Use at least 10 characters.";
      if (form.password !== form.password_confirm) local.password_confirm = "The two passwords don't match.";
    }
    if (Object.keys(local).length) { setErrors(local); return; }
    const body = {
      first_name: form.first_name.trim(), last_name: form.last_name.trim(), username: form.username.trim(),
      email: form.email.trim(), phone: form.phone.trim(), role: form.role ? Number(form.role) : null, is_active: form.is_active,
      staff_kind: form.staff_kind, company: form.staff_kind === "outsourced" ? form.company.trim() : "",
    };
    if (ownerView && form.staff_kind === "store") body.stock_point = form.stock_point ? Number(form.stock_point) : null;
    if (!editing && form.mode === "set") Object.assign(body, { password: form.password, password_confirm: form.password_confirm });
    setBusy(true);
    try {
      const saved = editing ? await api.patch(`/users/${user.id}/`, body) : await api.post("/users/", body);
      if (editing) onSaved(saved);
      else onCreated(saved);
    } catch (err) {
      setErrors(apiErrors(err, editing ? "Couldn't save these changes." : "Couldn't create the account."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog title={editing ? `Edit ${personName(user)}` : "Add new staff"} busy={busy} onClose={onClose}
      subtitle={editing ? "Role and Store Location changes apply on their next request." : "The account can sign in once it has a password."}
      footer={<>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" form="st-staff-form" className="st-btn" data-variant="primary" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Create account"}</button>
      </>}>
      <form id="st-staff-form" onSubmit={submit} noValidate className="st-grid">
        {errors._form && <Alert>{errors._form}</Alert>}
        <div className="st-grid" data-cols="2">
          <TextInput label="First name" value={form.first_name} onChange={set("first_name")} error={errors.first_name} autoComplete="off" autoFocus />
          <TextInput label="Last name" value={form.last_name} onChange={set("last_name")} error={errors.last_name} autoComplete="off" />
        </div>
        <TextInput label="Username" value={form.username} onChange={set("username")} error={errors.username} autoComplete="off" hint="Used to sign in. Letters, digits and @ . + - _ only." />
        <div className="st-grid" data-cols="2">
          <TextInput label="Email (optional)" type="email" value={form.email} onChange={set("email")} error={errors.email} autoComplete="off" />
          <TextInput label="Phone (optional)" type="tel" value={form.phone} onChange={set("phone")} error={errors.phone} autoComplete="off" />
        </div>
        <div className="st-grid" data-cols="2">
          <SelectInput label="Role" value={form.role} onChange={set("role")} error={errors.role}
            hint={ownerView ? undefined : "Only roles within your own permissions are listed."}>
            <option value="">No role (no module access)</option>
            {roleOptions.map((r) => <option key={r.id} value={String(r.id)}>{r.label}</option>)}
          </SelectInput>
          {form.staff_kind !== "store" ? (
            <div className="st-field">
              <span className="st-label">Store Location</span>
              <span className="st-input flex items-center" aria-readonly="true">Not tied to a store</span>
              <span className="st-help">Takes on-site jobs from any store.</span>
            </div>
          ) : ownerView ? (
            <SelectInput label="Store Location" value={form.stock_point} onChange={set("stock_point")} error={errors.stock_point}
              hint="Physical shops only. Unassigned staff see no store's data.">
              <option value="">Unassigned</option>
              {/* no new assignments to an inactive shop -- but keep the one this person already has */}
              {shops.filter((s) => s.is_active !== false || (editing && s.id === user.stock_point)).map((s) => (
                <option key={s.id} value={String(s.id)}>{s.name}{s.is_active === false ? " (inactive)" : ""}</option>
              ))}
            </SelectInput>
          ) : (
            <div className="st-field">
              <span className="st-label">Store Location</span>
              <span className="st-input flex items-center" aria-readonly="true">{editing ? user.stock_point_name || "Unassigned" : me.stock_point_name}</span>
              <span className="st-help">Only the Owner changes Store Locations.</span>
            </div>
          )}
        </div>
        <div className="st-grid" data-cols="2">
          <SelectInput label="Works as" value={form.staff_kind} onChange={set("staff_kind")} error={errors.staff_kind}
            hint="Field technicians and outsourced technicians belong to no store. The role must allow on-site work.">
            <option value="store">Store staff (one store)</option>
            <option value="field">Field technician (any store)</option>
            {(me.is_superuser || (me.permissions || []).includes("leads.outsource") || form.staff_kind === "outsourced") && <option value="outsourced">Outsourced technician (external)</option>}
          </SelectInput>
          {form.staff_kind === "outsourced" && (
            <TextInput label="Freelancer / company name" value={form.company} onChange={set("company")} error={errors.company} autoComplete="off" />
          )}
        </div>
        <label className="st-switch">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active")(e.target.checked)} />
          Account active (can sign in)
        </label>
        {!editing && (
          <fieldset className="st-grid">
            <legend className="st-label mb-2">Password</legend>
            <div className="st-choice">
              <label>
                <input type="radio" name="pw-mode" checked={form.mode === "link"} onChange={() => set("mode")("link")} />
                <span><b>Let them choose it (recommended)</b><span>After creating, generate a one-time setup link to give them. No one else ever knows the password.</span></span>
              </label>
              <label>
                <input type="radio" name="pw-mode" checked={form.mode === "set"} onChange={() => set("mode")("set")} />
                <span><b>Set an initial password</b><span>Tell it to them privately and ask them to change it under Settings → My password.</span></span>
              </label>
            </div>
            {form.mode === "set" && (
              <div className="st-grid" data-cols="2">
                <PasswordInput label="Initial password" value={form.password} onChange={set("password")} error={errors.password} hint="At least 10 characters." />
                <PasswordInput label="Confirm password" value={form.password_confirm} onChange={set("password_confirm")} error={errors.password_confirm} />
              </div>
            )}
          </fieldset>
        )}
      </form>
    </Dialog>
  );
}

function CreatedDialog({ user, onClose, onSetup }) {
  const pending = user.password_set === false;
  return (
    <Dialog title="Staff account created" onClose={onClose}
      footer={<>
        <button type="button" className="st-btn" onClick={onClose}>Done</button>
        {pending && <button type="button" className="st-btn" data-variant="primary" onClick={onSetup}><Link2 size={14} aria-hidden="true" />Create setup link</button>}
      </>}>
      <Alert tone="ok">{personName(user)} (<span className="st-mono">@{user.username}</span>) was created.</Alert>
      <dl className="st-kv">
        <dt>Role</dt><dd>{user.role_label || "No role"}</dd>
        <dt>Store Location</dt><dd>{user.stock_point_name || "Unassigned"}</dd>
        <dt>Status</dt><dd>{user.is_active ? "Active" : "Inactive"}</dd>
      </dl>
      {pending
        ? <Alert tone="warn">Next step: the account has no password yet. Create a one-time setup link and give it to {user.first_name || "them"} directly.</Alert>
        : <Alert tone="info">Share the initial password privately and ask them to change it under Settings → My password.</Alert>}
    </Dialog>
  );
}

function ResetDialog({ user, fresh, onClose }) {
  const [delivery, setDelivery] = useState("link");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post(`/users/${user.id}/reset-password/`, { delivery }));
    } catch (err) {
      setError(apiErrors(err, "Couldn't reset the password.")._form);
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(result.setup_url); setCopied(true); } catch { setCopied(false); }
  };

  return (
    <Dialog title={fresh ? `Set up ${personName(user)}'s password` : `Reset password — ${personName(user)}`} busy={busy} onClose={onClose}
      subtitle={<>Account <span className="st-mono">@{user.username}</span>{user.stock_point_name ? ` · ${user.stock_point_name}` : ""}</>}
      footer={result ? <button type="button" className="st-btn" data-variant="primary" onClick={onClose}>Done</button> : <>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="st-btn" data-variant="primary" onClick={run} disabled={busy}>{busy ? "Working…" : delivery === "email" ? "Reset and email link" : "Reset and create link"}</button>
      </>}>
      {!result && (
        <>
          {!fresh && <Alert tone="warn">Only this account is affected: its current password stops working and it's signed out everywhere. They then choose a new password through a single-use link valid for 24 hours.</Alert>}
          <div className="st-choice" role="radiogroup" aria-label="How to deliver the link">
            <label>
              <input type="radio" name="delivery" checked={delivery === "link"} onChange={() => setDelivery("link")} />
              <span><b><Link2 size={13} className="inline" aria-hidden="true" /> One-time link</b><span>Shown to you once — give it to them in person or over a channel you trust.</span></span>
            </label>
            <label>
              <input type="radio" name="delivery" checked={delivery === "email"} onChange={() => setDelivery("email")} disabled={!user.email} />
              <span><b><Mail size={13} className="inline" aria-hidden="true" /> Email the link</b><span>{user.email ? `To ${user.email}. Works only if this server has a real email provider configured.` : "No email address on file for this account."}</span></span>
            </label>
          </div>
          {error && <Alert>{error}</Alert>}
        </>
      )}
      {result?.delivery === "email" && <Alert tone="ok">The email provider accepted the message for {result.email}. The link expires in {result.expires_in_hours} hours.</Alert>}
      {result?.delivery === "link" && (
        <>
          <Alert tone="ok">Done. Give this link to {user.first_name || "them"} — it works once and expires in {result.expires_in_hours} hours. It won't be shown again.</Alert>
          <div className="st-link-box">
            <code>{result.setup_url}</code>
            <button type="button" className="st-btn" onClick={copy}>{copied ? <><Check size={14} aria-hidden="true" />Copied</> : <><Copy size={14} aria-hidden="true" />Copy</>}</button>
          </div>
        </>
      )}
    </Dialog>
  );
}

function ActiveDialog({ user, onClose, onDone }) {
  const deactivate = user.is_active;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/users/${user.id}/set-active/`, { is_active: !deactivate });
      onDone(`${personName(user)} was ${deactivate ? "deactivated and signed out" : "reactivated"}.`);
    } catch (err) {
      setError(apiErrors(err)._form);
      setBusy(false);
    }
  };
  return (
    <Dialog title={deactivate ? "Deactivate staff account?" : "Reactivate staff account?"} busy={busy} onClose={onClose}
      footer={<>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="st-btn" data-variant={deactivate ? "danger" : "primary"} onClick={run} disabled={busy}>{busy ? "Working…" : deactivate ? "Deactivate" : "Reactivate"}</button>
      </>}>
      <dl className="st-kv">
        <dt>Name</dt><dd>{personName(user)}</dd>
        <dt>Username</dt><dd className="st-mono">@{user.username}</dd>
        <dt>Role</dt><dd>{user.role_label || "No role"}</dd>
        <dt>Store</dt><dd>{user.stock_point_name || "Unassigned"}</dd>
      </dl>
      <p className="st-note">{deactivate
        ? "They're signed out and can't sign in until reactivated. Their history (invoices, repairs, audit entries) stays intact."
        : "They can sign in again with their existing password, with the same role and Store Location."}</p>
      {error && <Alert>{error}</Alert>}
    </Dialog>
  );
}

function DeleteDialog({ user, onClose, onDone, onDeactivate }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.del(`/users/${user.id}/`);
      onDone(`${personName(user)}'s account was deleted.`);
    } catch (err) {
      if (err.status === 409) setHistory(err.body);
      else setError(apiErrors(err)._form);
      setBusy(false);
    }
  };
  return (
    <Dialog title="Delete staff account?" busy={busy} onClose={onClose}
      footer={history ? <>
        <button type="button" className="st-btn" onClick={onClose}>Close</button>
        {user.is_active && <button type="button" className="st-btn" data-variant="primary" onClick={onDeactivate}><Power size={14} aria-hidden="true" />Deactivate instead</button>}
      </> : <>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="st-btn" data-variant="danger" onClick={run} disabled={busy}>{busy ? "Deleting…" : "Delete permanently"}</button>
      </>}>
      <dl className="st-kv">
        <dt>Name</dt><dd>{personName(user)}</dd>
        <dt>Username</dt><dd className="st-mono">@{user.username}</dd>
        <dt>Role</dt><dd>{user.role_label || "No role"}</dd>
        <dt>Store</dt><dd>{user.stock_point_name || "Unassigned"}</dd>
      </dl>
      {history ? (
        <Alert tone="warn">
          <b>This account can't be deleted.</b> {history.detail}
          {history.related_records?.length > 0 && <> Linked records: {history.related_records.join(", ")}.</>}
        </Alert>
      ) : (
        <p className="st-note">This permanently removes the account. It's only allowed for accounts with no business or audit history — otherwise you'll be offered deactivation instead.</p>
      )}
      {error && <Alert>{error}</Alert>}
    </Dialog>
  );
}
