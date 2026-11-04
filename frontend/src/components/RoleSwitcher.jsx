import { useState } from "react";
import { ChevronDown, UserCog } from "lucide-react";
import { useSession } from "../context/SessionContext";

/*
 * The role the account works under, from its own assigned roles (GET
 * /users/me/ -> assigned_roles). Switching only sends the choice; the server
 * checks it is assigned and applies that role's permissions to every
 * request (accounts.context). One role, or a superuser: shown, not a menu.
 */
export default function RoleSwitcher({ className = "", style }) {
  const { me, switchRole, switching } = useSession();
  const [error, setError] = useState("");
  if (!me) return null;

  const roles = me.assigned_roles || [];
  const base = `inline-flex h-9 items-center gap-2 rounded-xl px-3 text-xs font-bold ${className}`;
  const fixed = me.is_superuser ? "Superuser" : roles[0]?.label || me.role_label;
  if (me.is_superuser || roles.length < 2) {
    return fixed ? (
      <span className={base} style={style} title="Your role">
        <UserCog size={14} /><span className="hidden sm:inline">{fixed}</span>
      </span>
    ) : null;
  }

  const change = async (e) => {
    setError("");
    try {
      await switchRole(Number(e.target.value));
    } catch (err) {
      setError(err.message || "Couldn't switch role.");
    }
  };

  return (
    <label className={`relative ${base} cursor-pointer transition hover:-translate-y-0.5`} style={style} title={error || "Switch role"}>
      <UserCog size={14} aria-hidden="true" />
      <span className="sr-only">Active role</span>
      <select
        value={me.active_role ?? ""}
        onChange={change}
        disabled={switching}
        aria-invalid={!!error}
        className="cursor-pointer appearance-none bg-transparent pr-4 font-bold outline-none disabled:cursor-wait"
        style={{ color: "inherit", fontFamily: "inherit" }}
      >
        {roles.map((r) => <option key={r.id} value={r.id} style={{ color: "#111" }}>{r.label}</option>)}
      </select>
      <ChevronDown size={13} aria-hidden="true" className="pointer-events-none absolute right-2.5" />
      {error && <span role="alert" className="sr-only">{error}</span>}
    </label>
  );
}
