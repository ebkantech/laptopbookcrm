import { useState } from "react";
import { X } from "lucide-react";
import { C, F } from "../../lib/theme";
import { ErrorNote, Eyebrow } from "../Atoms";

export const inputStyle = (bad) => ({ border: `1px solid ${bad ? C.carbon : C.rule}`, color: C.ink, fontFamily: F.body });

export function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center p-0 sm:items-center sm:p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div role="dialog" aria-label={title} data-panel className={`max-h-[92vh] w-full overflow-y-auto p-5 sm:p-6 ${wide ? "max-w-3xl" : "max-w-md"}`} style={{ backgroundColor: C.slip }} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <Eyebrow>{title}</Eyebrow>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* A small form in a dialog. fields: [{ name, label, type, required, options, placeholder, hint }].
 * onSubmit(values) may throw -- its message is shown and the dialog stays open. */
export default function Prompt({ title, intro, fields, submitLabel = "Save", tone = C.orange, initial = {}, onSubmit, onClose }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.name, initial[f.name] ?? (f.type === "checkbox" ? false : "")])));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (name, v) => { setValues((old) => ({ ...old, [name]: v })); setError(""); };
  const missing = fields.find((f) => f.required && !String(values[f.name] ?? "").trim());

  const submit = async (e) => {
    e.preventDefault();
    if (missing) { setError(`${missing.label} is required.`); return; }
    setBusy(true);
    setError("");
    try {
      await onSubmit(values);
    } catch (err) {
      setError(err.message || "Something went wrong.");
      setBusy(false);
    }
  };

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {intro && <p className="text-xs" style={{ color: C.inkSoft, fontFamily: F.body }}>{intro}</p>}
        {fields.map((f) => (
          <label key={f.name} className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
            {f.type === "checkbox" ? (
              <span className="flex items-start gap-2"><input type="checkbox" checked={!!values[f.name]} onChange={(e) => set(f.name, e.target.checked)} className="mt-0.5 h-4 w-4" /><span style={{ color: C.ink }}>{f.label}</span></span>
            ) : (
              <>
                {f.label}{f.required && " *"}
                {f.type === "textarea" ? (
                  <textarea value={values[f.name]} onChange={(e) => set(f.name, e.target.value)} rows={3} placeholder={f.placeholder} maxLength={f.maxLength} className="mt-1 w-full resize-none bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
                ) : f.type === "select" ? (
                  <select value={values[f.name]} onChange={(e) => set(f.name, e.target.value)} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)}>
                    {f.options.map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
                  </select>
                ) : (
                  <input type={f.type || "text"} value={values[f.name]} onChange={(e) => set(f.name, e.target.value)} placeholder={f.placeholder} max={f.max} min={f.min} inputMode={f.inputMode} className="mt-1 w-full bg-transparent px-3 py-2 text-base outline-none sm:text-sm" style={inputStyle(false)} />
                )}
              </>
            )}
            {f.hint && <span className="mt-1 block">{f.hint}</span>}
          </label>
        ))}
        <ErrorNote message={error} />
        <button disabled={busy} className="flex min-h-[44px] w-full items-center justify-center py-2.5 text-xs uppercase" style={{ backgroundColor: tone, color: C.onAccent, fontFamily: F.body, fontWeight: 700, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>{busy ? "Please wait…" : submitLabel}</button>
      </form>
    </Modal>
  );
}
