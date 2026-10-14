import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal, Pencil, X } from "lucide-react";
import { C, F } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote } from "../Atoms";

export function PartyActionsMenu({ onEdit }) {
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  const close = () => setOpen(false);
  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({
      top: Math.min(rect.bottom + 5, window.innerHeight - 100),
      left: Math.max(8, Math.min(rect.right - 192, window.innerWidth - 200)),
    });
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (!triggerRef.current?.contains(event.target) && !menuRef.current?.contains(event.target)) close();
    };
    const onKeyDown = (event) => { if (event.key === "Escape") { close(); triggerRef.current?.focus(); } };
    const onScroll = () => close();
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    menuRef.current?.querySelector("button")?.focus();
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  return <>
    <button
      ref={triggerRef}
      type="button"
      aria-label="Customer actions"
      aria-haspopup="menu"
      aria-expanded={open}
      onClick={(event) => { event.stopPropagation(); if (open) close(); else show(); }}
      className="flex h-9 w-9 items-center justify-center rounded-lg opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 focus-visible:opacity-100"
      style={{ color: C.inkSoft, background: "transparent" }}
    ><MoreHorizontal size={19} /></button>
    {open && createPortal(
      <div ref={menuRef} role="menu" aria-label="Customer actions" className="fixed z-[100] w-48 rounded-xl p-1.5" style={{ top: position.top, left: position.left, background: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 12px 32px rgba(23,32,51,.18)" }}>
        <button role="menuitem" type="button" onClick={(event) => { event.stopPropagation(); close(); onEdit(); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-slate-50" style={{ color: C.ink }}><Pencil size={15} />Edit customer</button>
      </div>, document.body,
    )}
  </>;
}

export function LinkActionsMenu({ items, label = "Link actions" }) {
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const close = () => setOpen(false);
  const toggle = (event) => {
    event.stopPropagation();
    if (open) return close();
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({ top: Math.min(rect.bottom + 5, window.innerHeight - 100), left: Math.max(8, Math.min(rect.right - 192, window.innerWidth - 200)) });
    setOpen(true);
  };
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => { if (!triggerRef.current?.contains(event.target) && !menuRef.current?.contains(event.target)) close(); };
    const onKeyDown = (event) => { if (event.key === "Escape") { close(); triggerRef.current?.focus(); } };
    const onScroll = () => close();
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    menuRef.current?.querySelector("button")?.focus();
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);
  return <>
    <button ref={triggerRef} type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={toggle} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ color: C.inkSoft }}><MoreHorizontal size={18} /></button>
    {open && createPortal(<div ref={menuRef} role="menu" aria-label={label} className="fixed z-[110] w-48 rounded-xl p-1.5" style={{ top: position.top, left: position.left, background: C.slip, border: `1px solid ${C.rule}`, boxShadow: "0 12px 32px rgba(23,32,51,.18)" }}>
      {items.map(({ label: itemLabel, icon: Icon, onSelect, danger = false, disabled = false }) => <button key={itemLabel} role="menuitem" type="button" disabled={disabled} aria-disabled={disabled || undefined} onClick={(event) => { event.stopPropagation(); if (disabled) return; close(); onSelect(); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-55" style={{ color: danger ? C.carbon : C.ink }}><Icon size={15} />{itemLabel}</button>)}
    </div>, document.body)}
  </>;
}

export function PartyEditModal({ party, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: party.name || "", phone: party.phone || "", email: party.email || "",
    city: party.city || "", type: party.type || "Retail", gstin: party.gstin || "",
    customer_classification: party.customer_classification || "individual",
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }));
    setErrors((current) => ({ ...current, [key]: "" }));
  };

  useEffect(() => {
    const onKeyDown = (event) => { if (event.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    const cleaned = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim()]));
    const nextErrors = {};
    if (!cleaned.name) nextErrors.name = "Enter the customer's name.";
    const digits = cleaned.phone.replace(/\D/g, "");
    if (digits.length < 10 || digits.length > 15) nextErrors.phone = "Enter a valid phone number with 10 to 15 digits.";
    if (!cleaned.email) nextErrors.email = "Enter the customer's email address.";
    if (!cleaned.city) nextErrors.city = "Enter the customer's city.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setBusy(true);
    try {
      const updated = await api.patch(`/parties/${party.id}/`, cleaned);
      onSaved(updated);
    } catch (e) {
      const body = e.body || {};
      const apiErrors = Object.fromEntries(Object.entries(body).filter(([key]) => key !== "detail").map(([key, value]) => [key, [].concat(value).join(" ")]));
      setErrors(apiErrors);
      setError(body.detail || (!Object.keys(apiErrors).length ? e.message : "Please correct the highlighted fields."));
    } finally {
      setBusy(false);
    }
  };

  const field = (label, key, props = {}) => <label className="block min-w-0 text-sm" style={{ color: C.inkSoft }}>
    {label}
    <input value={form[key]} onChange={set(key)} {...props} aria-invalid={!!errors[key]} className="mt-1.5 w-full rounded-lg px-3 py-2.5 text-sm outline-none" style={{ color: C.ink, background: C.slip, border: `1px solid ${errors[key] ? C.carbon : C.rule}` }} />
    {errors[key] && <span className="mt-1 block text-xs" style={{ color: C.carbon }}>{errors[key]}</span>}
  </label>;

  return <div className="fixed inset-0 z-[60] flex items-end justify-center bg-slate-950/55 p-0 backdrop-blur-[2px] sm:items-center sm:p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form role="dialog" aria-modal="true" aria-labelledby="party-edit-title" onSubmit={submit} className="max-h-[94dvh] w-full max-w-xl overflow-y-auto rounded-t-2xl p-5 sm:rounded-2xl sm:p-6" data-panel style={{ background: C.slip }}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 id="party-edit-title" className="text-lg font-bold" style={{ color: C.ink, fontFamily: F.display }}>Edit customer</h2><p className="mt-1 text-sm" style={{ color: C.inkSoft }}>Update {party.name}'s saved details.</p></div>
        <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ color: C.inkSoft }}><X size={18} /></button>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {field("Name *", "name", { required: true, autoFocus: true })}
        {field("Mobile *", "phone", { required: true, inputMode: "tel" })}
        {field("Email *", "email", { required: true, type: "email" })}
        {field("City *", "city", { required: true })}
        <label className="block text-sm" style={{ color: C.inkSoft }}>Type *<select value={form.type} onChange={set("type")} required className="mt-1.5 w-full rounded-lg px-3 py-2.5 text-sm" style={{ color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }}><option>Retail</option><option>Dealer</option><option>Rental</option></select></label>
        <label className="block text-sm" style={{ color: C.inkSoft }}>Customer classification<select value={form.customer_classification} onChange={set("customer_classification")} className="mt-1.5 w-full rounded-lg px-3 py-2.5 text-sm" style={{ color: C.ink, background: C.slip, border: `1px solid ${C.rule}` }}><option value="individual">Individual</option><option value="business">Business / Corporate</option><option value="dealer">Dealer</option></select></label>
        {field("GSTIN (optional)", "gstin")}
      </div>
      <ErrorNote message={error} />
      <div className="mt-6 flex flex-col-reverse justify-end gap-2 sm:flex-row">
        <button type="button" disabled={busy} onClick={onClose} className="rounded-lg px-4 py-2.5 text-sm font-semibold" style={{ color: C.inkSoft, border: `1px solid ${C.rule}` }}>Cancel</button>
        <button type="submit" disabled={busy} className="rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" style={{ background: C.stamp }}>{busy ? "Saving…" : "Save changes"}</button>
      </div>
    </form>
  </div>;
}
