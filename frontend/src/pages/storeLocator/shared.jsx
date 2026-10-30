import { CircleCheck, CircleOff, Globe, Lock, Search, Store } from "lucide-react";
import { isShop, num } from "./format";

/*
 * Small building blocks shared by the Store & Channel Management page
 * (pages/StoreLocator.jsx) and its views. Styles: pages/StoreLocator.css.
 */

export function Badge({ tone = "blue", icon: Icon, children, title }) {
  return (
    <span className="sl-badge" data-tone={tone} title={title}>
      {Icon && <Icon size={11} aria-hidden="true" />}
      {children}
    </span>
  );
}

export function KindBadge({ sp }) {
  return isShop(sp)
    ? <Badge icon={Store}>Shop</Badge>
    : <Badge tone="violet" icon={Globe}>Online channel</Badge>;
}

// Active / Inactive -- the API only sends is_active to administrators
// (catalog.status), so for everyone else this renders nothing.
export function StatusBadge({ sp }) {
  if (typeof sp?.is_active !== "boolean") return null;
  return sp.is_active
    ? <Badge tone="green" icon={CircleCheck}>Active</Badge>
    : <Badge tone="grey" icon={CircleOff} title="New operations are blocked at this shop / channel">Inactive</Badge>;
}

export function StoreMark({ sp, size = "md" }) {
  return (
    <span className="sl-mark" data-kind={sp.kind} data-size={size} aria-hidden="true">
      {isShop(sp) ? <Store size={size === "lg" ? 22 : size === "sm" ? 15 : 18} /> : <Globe size={size === "lg" ? 22 : size === "sm" ? 15 : 18} />}
    </span>
  );
}

export function StateBox({ icon: Icon = Search, title, text, tone, compact = false, action }) {
  return (
    <div className="sl-state" data-tone={tone} data-compact={compact} role={tone === "error" ? "alert" : undefined}>
      <span className="sl-state-icon"><Icon size={18} aria-hidden="true" /></span>
      <p className="sl-state-title">{title}</p>
      {text && <p className="sl-state-text">{text}</p>}
      {action}
    </div>
  );
}

export function Restricted({ what }) {
  return (
    <StateBox
      compact
      icon={Lock}
      title={`${what} aren't available for your role`}
      text="Your role doesn't include the permission this section needs. Ask an administrator if you should have access."
    />
  );
}

export function Panel({ icon: Icon, title, action, children, className = "" }) {
  return (
    <section className={`sl-panel ${className}`} aria-label={title}>
      <header className="sl-panel-head">
        <h3 className="sl-panel-title">{Icon && <Icon size={14} aria-hidden="true" />}{title}</h3>
        {action}
      </header>
      {children}
    </section>
  );
}

export function Skel({ w = "100%", h = 12, r = 6, className = "" }) {
  return <span className={`sl-skel ${className}`} style={{ width: w, height: h, borderRadius: r }} aria-hidden="true" />;
}

export function Kpi({ label, value, hint }) {
  return (
    <div className="sl-kpi">
      <p className="sl-kpi-value">{value}</p>
      <p className="sl-kpi-label">{label}</p>
      {hint && <p className="sl-kpi-hint">{hint}</p>}
    </div>
  );
}

/* Segmented filter: [{ id, label, count? }] */
export function Segmented({ label, options, value, onChange }) {
  return (
    <div className="sl-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onChange(o.id)}>
          {o.label}
          {o.count !== undefined && o.count !== null && <span className="sl-seg-count">{num(o.count)}</span>}
        </button>
      ))}
    </div>
  );
}

export function SelectPill({ label, value, onChange, children, disabled }) {
  return (
    <label className="sl-select">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>{children}</select>
    </label>
  );
}
