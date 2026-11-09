import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Asterisk, Plus, Trash2, X } from "lucide-react";
import { api } from "../../lib/api";
import { ICONS, loadCategories } from "./categories";

const TYPES = [["text", "Text"], ["choice", "Fixed choice"], ["long", "Long text"]];
const listText = (arr) => (arr || []).join(", ");
const toList = (text) => String(text || "").split(",").map((x) => x.trim()).filter(Boolean);

const blankCategory = () => ({
  id: null, name: "", icon: "package", is_active: true, name_label: "Product name", brand_required: false,
  show_condition: false, code_prefix: "VC-ACC", product_count: 0,
  fields: [{ label: "", type: "text", required: false, summary: true, optionsText: "", suggestText: "" }],
});
const draftOf = (c) => ({
  ...c,
  fields: (c.fields || []).map((f) => ({ ...f, optionsText: listText(f.options), suggestText: listText(f.suggest) })),
});

/*
 * Inventory -> Add stock -> Edit categories (Owner / Admin only): rename a
 * category, pick its icon, add / rename / remove / reorder the details its
 * form asks for, mark any of them required (*) or a fixed choice -- e.g. a
 * furniture shop drops Processor/RAM and asks Material, Colour shade, Size.
 * Renaming keeps every product already saved under the category or field.
 */
export default function CategoryEditor({ categories, onClose, onSaved }) {
  const [list, setList] = useState(categories);
  const [selected, setSelected] = useState(categories[0]?.id ?? "new");
  const [draft, setDraft] = useState(() => (categories[0] ? draftOf(categories[0]) : blankCategory()));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const pick = (c) => {
    if (dirty && !window.confirm("Discard the changes to this category?")) return;
    setSelected(c ? c.id : "new");
    setDraft(c ? draftOf(c) : blankCategory());
    setDirty(false); setError(""); setNote("");
  };
  const edit = (patch) => { setDraft((d) => ({ ...d, ...patch })); setDirty(true); };
  const editField = (i, patch) => edit({ fields: draft.fields.map((f, n) => (n === i ? { ...f, ...patch } : f)) });
  const moveField = (i, by) => {
    const fields = [...draft.fields];
    const j = i + by;
    if (j < 0 || j >= fields.length) return;
    [fields[i], fields[j]] = [fields[j], fields[i]];
    edit({ fields });
  };

  const refresh = async (keepId) => {
    const fresh = await loadCategories();
    setList(fresh);
    onSaved(fresh);
    const now = fresh.find((c) => c.id === keepId);
    if (now) { setSelected(now.id); setDraft(draftOf(now)); }
    return fresh;
  };

  const save = async () => {
    setError(""); setNote("");
    if (!draft.name.trim()) return setError("Enter the category name.");
    const body = {
      name: draft.name.trim(), icon: draft.icon, is_active: draft.is_active, name_label: draft.name_label,
      brand_required: draft.brand_required, show_condition: draft.show_condition, code_prefix: draft.code_prefix,
      fields: draft.fields.filter((f) => f.label.trim()).map((f) => ({
        key: f.key, label: f.label.trim(), type: f.type, required: !!f.required, summary: !!f.summary, placeholder: f.placeholder || "",
        options: f.type === "choice" ? toList(f.optionsText) : [], suggest: f.type === "text" ? toList(f.suggestText) : [],
      })),
    };
    setBusy(true);
    try {
      const saved = draft.id ? await api.patch(`/product-categories/${draft.id}/`, body) : await api.post("/product-categories/", body);
      await refresh(saved.id);
      setDirty(false);
      setNote(`${saved.name} saved — the Add stock form uses it straight away.`);
    } catch (e) {
      const b = e.body || {};
      setError([].concat(b.name || [], b.fields || [], b.code_prefix || [], b.detail || []).join(" ") || e.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    const inUse = draft.product_count > 0;
    if (!window.confirm(inUse
      ? `${draft.name} has ${draft.product_count} product(s), so it will be switched off (hidden from Add stock), not deleted. Continue?`
      : `Delete the category ${draft.name}? This can't be undone.`)) return;
    setBusy(true); setError("");
    try {
      await api.del(`/product-categories/${draft.id}/`);
      const fresh = await refresh(inUse ? draft.id : null);
      if (!inUse) { setSelected(fresh[0]?.id ?? "new"); setDraft(fresh[0] ? draftOf(fresh[0]) : blankCategory()); }
      setDirty(false);
      setNote(inUse ? `${draft.name} is switched off.` : "Category deleted.");
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const Icon = ICONS[draft.icon] || ICONS.package;
  const required = useMemo(() => draft.fields.filter((f) => f.required).length, [draft.fields]);

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-slate-950/60 sm:items-center sm:p-4" onClick={() => !busy && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Edit product categories" className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div>
            <p className="text-base font-semibold text-slate-900">Edit product categories</p>
            <p className="text-xs text-slate-500">Rename categories and choose what each one asks for. Tick <b>*</b> to make a detail required.</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-slate-100"><X size={18} /></button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto sm:grid-cols-[220px_minmax(0,1fr)] sm:overflow-hidden">
          {/* the categories */}
          <div className="border-b border-slate-200 p-3 sm:overflow-y-auto sm:border-b-0 sm:border-r">
            <ul className="space-y-1">
              {list.map((c) => {
                const CIcon = ICONS[c.icon] || ICONS.package;
                return (
                  <li key={c.id}>
                    <button type="button" onClick={() => pick(c)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm ${selected === c.id ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-700 hover:bg-slate-50"}`}>
                      <CIcon size={16} className="shrink-0" />
                      <span className="min-w-0 flex-1 truncate">{c.name}</span>
                      {!c.is_active && <span className="rounded bg-slate-200 px-1.5 text-[10px] text-slate-600">off</span>}
                      <span className="text-[11px] text-slate-400">{c.product_count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <button type="button" onClick={() => pick(null)} className={`mt-2 flex w-full items-center gap-1.5 rounded-lg border border-dashed px-2.5 py-2 text-sm ${selected === "new" ? "border-blue-400 text-blue-700" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
              <Plus size={15} /> New category
            </button>
          </div>

          {/* one category */}
          <div className="min-w-0 p-4 sm:overflow-y-auto sm:p-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="text-xs font-medium text-slate-600">Category name *
                <input value={draft.name} maxLength={40} onChange={(e) => edit({ name: e.target.value })} placeholder="e.g. Office chair"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-2.5 py-2 text-sm text-slate-900" />
              </label>
              <label className="text-xs font-medium text-slate-600">Name box is called
                <input value={draft.name_label} maxLength={40} onChange={(e) => edit({ name_label: e.target.value })}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-2.5 py-2 text-sm text-slate-900" />
              </label>
              <label className="text-xs font-medium text-slate-600">Product ID starts with
                <input value={draft.code_prefix} maxLength={11} onChange={(e) => edit({ code_prefix: e.target.value.toUpperCase() })}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-2.5 py-2 font-mono text-sm text-slate-900" />
              </label>
            </div>

            <p className="mt-3 text-xs font-medium text-slate-600">Icon</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {Object.entries(ICONS).map(([name, I]) => (
                <button key={name} type="button" title={name} onClick={() => edit({ icon: name })}
                  className={`flex h-9 w-9 items-center justify-center rounded-lg border ${draft.icon === name ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
                  <I size={17} />
                </button>
              ))}
            </div>

            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-700">
              <label className="flex items-center gap-2"><input type="checkbox" checked={draft.brand_required} onChange={(e) => edit({ brand_required: e.target.checked })} /> Brand is required *</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={draft.show_condition} onChange={(e) => edit({ show_condition: e.target.checked })} /> Ask condition (New / Refurbished / Used)</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={draft.is_active} onChange={(e) => edit({ is_active: e.target.checked })} /> Shown on Add stock</label>
            </div>
            <p className="mt-1 text-[11px] text-slate-400">Brand, name, colour, HSN, description and prices are always on the form.</p>

            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-800">Details this category asks for <span className="font-normal text-slate-500">· {draft.fields.length} · {required} required</span></p>
              <button type="button" onClick={() => edit({ fields: [...draft.fields, { label: "", type: "text", required: false, summary: false, optionsText: "", suggestText: "" }] })}
                className="flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <Plus size={13} /> Add detail
              </button>
            </div>

            <div className="mt-2 space-y-2">
              {draft.fields.map((f, i) => (
                <div key={f.key || `new-${i}`} className="rounded-xl border border-slate-200 p-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => editField(i, { required: !f.required })} title={f.required ? "Required — click to make optional" : "Optional — click to make required"}
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${f.required ? "border-red-300 bg-red-50 text-red-600" : "border-slate-200 text-slate-300 hover:text-slate-500"}`}
                      aria-pressed={!!f.required} aria-label={`${f.label || "This detail"} is required`}>
                      <Asterisk size={16} />
                    </button>
                    <input value={f.label} maxLength={40} onChange={(e) => editField(i, { label: e.target.value })} placeholder="Detail name, e.g. Material"
                      className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900" aria-label="Detail name" />
                    <select value={f.type} onChange={(e) => editField(i, { type: e.target.value })} aria-label="Type"
                      className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm text-slate-800">
                      {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <label className="flex items-center gap-1 text-xs text-slate-600" title="Shown in the short spec line on invoices and stock lists">
                      <input type="checkbox" checked={!!f.summary} onChange={(e) => editField(i, { summary: e.target.checked })} /> In spec line
                    </label>
                    <span className="flex items-center gap-0.5">
                      <button type="button" onClick={() => moveField(i, -1)} disabled={i === 0} aria-label="Move up" className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"><ArrowUp size={14} /></button>
                      <button type="button" onClick={() => moveField(i, 1)} disabled={i === draft.fields.length - 1} aria-label="Move down" className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"><ArrowDown size={14} /></button>
                      <button type="button" onClick={() => edit({ fields: draft.fields.filter((_, n) => n !== i) })} aria-label="Remove detail" className="rounded p-1 text-red-500 hover:bg-red-50"><Trash2 size={14} /></button>
                    </span>
                  </div>
                  {f.type === "choice" && (
                    <input value={f.optionsText} onChange={(e) => editField(i, { optionsText: e.target.value })} placeholder="Choices, separated by commas — e.g. Mesh, Leather, Fabric"
                      className="mt-2 block w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-800" aria-label="Choices" />
                  )}
                  {f.type === "text" && (
                    <input value={f.suggestText} onChange={(e) => editField(i, { suggestText: e.target.value })} placeholder="Suggestions while typing (optional), separated by commas"
                      className="mt-2 block w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600" aria-label="Suggestions" />
                  )}
                </div>
              ))}
              {!draft.fields.length && <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">No extra details — the form will ask only brand, name, colour, HSN and prices.</p>}
            </div>

            {/* what Add stock will show */}
            <div className="mt-4 rounded-xl bg-slate-50 p-3">
              <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-500"><Icon size={13} /> Preview · {draft.name || "New category"}</p>
              <p className="mt-1 text-xs text-slate-700">
                {draft.brand_required ? "Brand *" : "Brand"} · {draft.name_label || "Product name"} *
                {draft.fields.filter((f) => f.label.trim()).map((f) => ` · ${f.label.trim()}${f.required ? " *" : ""}${f.type === "choice" && toList(f.optionsText).length ? ` (${toList(f.optionsText).join("/")})` : ""}`).join("")}
                {draft.show_condition ? " · Condition" : ""} · Colour · HSN
              </p>
            </div>

            {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
            {note && <p className="mt-3 rounded-lg bg-green-50 px-3 py-2 text-xs text-green-700">{note}</p>}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-5 py-3">
          <div>
            {draft.id && (
              <button type="button" onClick={remove} disabled={busy} className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50">
                <Trash2 size={13} /> {draft.product_count ? "Switch off category" : "Delete category"}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={busy} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700">Close</button>
            <button type="button" onClick={save} disabled={busy || !dirty} className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
              {busy ? "Saving…" : draft.id ? "Save changes" : "Add category"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
