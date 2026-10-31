import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, EyeOff, Info, X } from "lucide-react";

/* Small building blocks for Settings > Staff management / My password.
   Styles: settings/staff.css. */

export function Alert({ tone = "error", children }) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "error" ? AlertTriangle : Info;
  return (
    <div className="st-alert" data-tone={tone} role={tone === "error" ? "alert" : "status"}>
      <Icon size={15} aria-hidden="true" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Field({ label, hint, error, children, id }) {
  return (
    <div className="st-field">
      <label className="st-label" htmlFor={id}>{label}</label>
      {children}
      {error ? <p className="st-err" id={`${id}-err`}>{error}</p> : hint ? <p className="st-help">{hint}</p> : null}
    </div>
  );
}

export function TextInput({ label, hint, error, value, onChange, type = "text", autoComplete, required, autoFocus, placeholder }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} id={id}>
      <input
        id={id} className="st-input" type={type} value={value} onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete} required={required} autoFocus={autoFocus} placeholder={placeholder}
        aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
      />
    </Field>
  );
}

export function PasswordInput({ label, hint, error, value, onChange, autoComplete = "new-password", autoFocus }) {
  const id = useId();
  const [show, setShow] = useState(false);
  return (
    <Field label={label} hint={hint} error={error} id={id}>
      <div className="st-pw">
        <input
          id={id} className="st-input" type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete} autoFocus={autoFocus} aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
        />
        <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>
          {show ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
        </button>
      </div>
    </Field>
  );
}

export function SelectInput({ label, hint, error, value, onChange, children, disabled }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} id={id}>
      <select id={id} className="st-input" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} aria-invalid={!!error}>
        {children}
      </select>
    </Field>
  );
}

/* Modal dialog: Escape and the close button dismiss it (unless `busy`),
   focus moves into it on open and returns to the opener on close. */
export function Dialog({ title, subtitle, onClose, busy, children, footer, labelledBy = "st-dialog-title", size, headExtra }) {
  const ref = useRef(null);
  useEffect(() => {
    const opener = document.activeElement;
    ref.current?.querySelector("input, select, textarea, button:not([data-close])")?.focus();
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
      if (e.key !== "Tab" || !ref.current) return;
      const items = [...ref.current.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')];
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [onClose, busy]);

  return (
    <div className="st-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div ref={ref} className="st-dialog" data-size={size} role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <div className="st-dialog-head">
          {headExtra}
          <div className="min-w-0 flex-1">
            <h2 id={labelledBy} className="st-dialog-title">{title}</h2>
            {subtitle && <div className="st-note mt-1">{subtitle}</div>}
          </div>
          <button type="button" data-close className="st-icon-btn" onClick={onClose} disabled={busy} aria-label="Close dialog">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="st-dialog-body">{children}</div>
        {footer && <div className="st-dialog-foot">{footer}</div>}
      </div>
    </div>
  );
}
