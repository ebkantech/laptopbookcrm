import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Camera, CheckCircle2, Copy, ImagePlus, Loader2, Plus, ShieldCheck, Trash2, X } from "lucide-react";

import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";
import { ErrorNote, Eyebrow } from "../Atoms";

const QUICK_ACCESSORIES = ["Charger", "Mouse", "Laptop bag", "Keyboard", "Headset", "HDMI cable"];
// Labels get an explicit display: the app's Bootstrap stylesheet sets
// label { display: inline-block } unlayered, which beats Tailwind's
// flex/block utility classes.
const field = { fontFamily: F.body, color: C.ink, background: C.slip, border: `1px solid ${C.rule}` };

// Phone photos are often 4-8 MB. Scale down to ~1600px JPEG before upload:
// plenty to show condition and read a serial label, a fraction of the size.
async function shrinkPhoto(file) {
  try {
    if (file.size < 900 * 1024) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob ? new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file; // browser can't decode it here (e.g. HEIC) -- let the server decide
  }
}

/* A photo behind the staff login, loaded with the auth header. */
function AuthImage({ photoId, alt }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url = null;
    let cancelled = false;
    api.blobUrl(`/rental-photos/${photoId}/`).then((u) => {
      url = u;
      if (cancelled) URL.revokeObjectURL(u);
      else setSrc(u);
    }).catch(() => {});
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [photoId]);
  return src
    ? <img src={src} alt={alt} className="h-full w-full object-cover" />
    : <div className="flex h-full w-full items-center justify-center"><Loader2 size={14} className="animate-spin" style={{ color: C.inkSoft }} /></div>;
}

function PhotoSlot({ label, photos, required, editable, onAdd, onDelete, busy }) {
  const input = useRef(null);
  return (
    <div data-photo-slot={label} className="p-2" style={{ border: `1px solid ${required && !photos.length ? C.amber : C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex items-center justify-between">
        <span className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{label}{required && <span style={{ color: C.carbon }}> *</span>}</span>
        {photos.length > 0 && <CheckCircle2 size={13} style={{ color: C.green }} />}
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
        {photos.map((p) => (
          <div key={p.id} className="relative aspect-[4/3] overflow-hidden" style={{ backgroundColor: C.paper }}>
            <AuthImage photoId={p.id} alt={label} />
            {editable && (
              <button type="button" onClick={() => onDelete(p)} title="Remove photo" className="absolute right-1 top-1 rounded-full p-0.5" style={{ backgroundColor: "rgba(0,0,0,0.55)" }}>
                <X size={11} color="#fff" />
              </button>
            )}
          </div>
        ))}
        {editable && (
          <button type="button" disabled={busy} onClick={() => input.current?.click()} className="flex aspect-[4/3] flex-col items-center justify-center gap-1 text-xs" style={{ border: `1px dashed ${C.rule}`, color: C.inkSoft, fontFamily: F.body }}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Camera size={16} />}
            {busy ? "Uploading…" : photos.length ? "Add another" : "Take / upload"}
          </button>
        )}
      </div>
      {/* capture=environment opens the rear camera on phones; desktops get a file picker */}
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onAdd(f); }} />
    </div>
  );
}

function DeviceHandover({ lineId, onSaved, allLineIds }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState("");

  const load = (body) => {
    setData(body);
    setForm({
      checks: body.checks || {}, working_confirmed: body.working_confirmed, condition_notes: body.condition_notes,
      accessories: body.accessories || [], warranty_included: body.warranty_included,
      warranty_months: body.warranty_months ?? "", warranty_terms: body.warranty_terms,
    });
  };

  useEffect(() => {
    api.get(`/rental-lines/${lineId}/handover/`).then(load).catch((e) => setError(e.message));
  }, [lineId]);

  if (error && !data) return <ErrorNote message={error} />;
  if (!data || !form) return <div className="flex items-center gap-2 p-6 text-sm" style={{ color: C.inkSoft }}><Loader2 size={14} className="animate-spin" /> Loading device…</div>;

  const editable = data.editable;
  const meta = data.meta;
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const flagRevoked = (res) => { if (res.approval_link_revoked) setNote("The approval link already sent was withdrawn — send a fresh one once the handover is complete."); };

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const res = await api.patch(`/rental-lines/${lineId}/handover/`, {
        ...form,
        warranty_months: form.warranty_months === "" ? null : Number(form.warranty_months),
        accessories: form.accessories.filter((a) => a.name.trim()),
      });
      load(res);
      flagRevoked(res);
      if (!res.approval_link_revoked) setNote("Saved.");
      onSaved();
    } catch (e) {
      const body = e.body || {};
      setError(body.detail || Object.entries(body).map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`).join(" · ") || e.message);
    } finally {
      setSaving(false);
    }
  };

  const addPhoto = async (kind, file) => {
    setUploading(kind);
    setError("");
    try {
      const fd = new FormData();
      fd.append("kind", kind);
      fd.append("image", await shrinkPhoto(file));
      const res = await api.upload(`/rental-lines/${lineId}/photos/`, fd);
      flagRevoked(res);
      load(await api.get(`/rental-lines/${lineId}/handover/`));
      onSaved();
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setUploading("");
    }
  };

  const deletePhoto = async (photo) => {
    if (!window.confirm(`Remove this ${photo.kind_label} photo?`)) return;
    try {
      flagRevoked(await api.del(`/rental-photos/${photo.id}/`));
      load(await api.get(`/rental-lines/${lineId}/handover/`));
      onSaved();
    } catch (e) {
      setError(e.body?.detail || e.message);
    }
  };

  const copyWarrantyToAll = async () => {
    const others = allLineIds.filter((id) => id !== lineId);
    if (!others.length) return;
    try {
      const payload = {
        warranty_included: form.warranty_included, warranty_terms: form.warranty_terms,
        warranty_months: form.warranty_months === "" ? null : Number(form.warranty_months),
      };
      await Promise.all(others.map((id) => api.patch(`/rental-lines/${id}/handover/`, payload)));
      setNote(`Warranty copied to the other ${others.length} device${others.length > 1 ? "s" : ""}.`);
      onSaved();
    } catch (e) {
      setError(e.body?.detail || e.message);
    }
  };

  const photosOf = (kind) => data.photos.filter((p) => p.kind === kind);
  const allChecked = meta.checks.every((c) => form.checks[c.key]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{data.description}</p>
          <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>Asset {data.asset_tag} · S/N {data.serial_number}</p>
        </div>
        {data.issues.length === 0
          ? <span className="flex items-center gap-1 text-xs" style={{ color: C.green, fontWeight: 600 }}><CheckCircle2 size={14} /> Ready for customer approval</span>
          : <span className="flex items-center gap-1 text-xs" style={{ color: C.amber, fontWeight: 600 }}><AlertTriangle size={14} /> {data.issues.length} item{data.issues.length > 1 ? "s" : ""} missing</span>}
      </div>
      {!editable && <p className="p-2 text-xs" style={{ backgroundColor: C.slip2, color: C.inkSoft }}>Locked — this is what the customer approved.</p>}
      {data.issues.length > 0 && (
        <ul className="space-y-0.5 p-2 text-xs" style={{ backgroundColor: `${C.amber}12`, color: C.ink }}>
          {data.issues.map((i) => <li key={i}>• {i}</li>)}
        </ul>
      )}

      <section>
        <Eyebrow>1 · Working condition</Eyebrow>
        <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
          {meta.checks.map((c) => (
            <label key={c.key} className="flex items-center gap-2 text-sm" style={{ display: "flex", color: C.ink }}>
              <input type="checkbox" disabled={!editable} checked={!!form.checks[c.key]} onChange={(e) => set("checks", { ...form.checks, [c.key]: e.target.checked })} /> {c.label}
            </label>
          ))}
        </div>
        {editable && !allChecked && (
          <button type="button" onClick={() => set("checks", Object.fromEntries(meta.checks.map((c) => [c.key, true])))} className="mt-1 text-xs underline" style={{ color: C.inkSoft }}>Tick all</button>
        )}
        <label className="mt-2 flex items-start gap-2 p-2 text-sm" style={{ display: "flex", backgroundColor: C.slip2, color: C.ink }}>
          <input type="checkbox" className="mt-1" disabled={!editable} checked={form.working_confirmed} onChange={(e) => set("working_confirmed", e.target.checked)} />
          I tested this device and confirm it is in working condition at handover.
        </label>
        <label className="mt-2 block text-xs" style={{ display: "block", color: C.inkSoft }}>Cosmetic condition (scratches, dents, wear)
          <textarea rows={2} disabled={!editable} value={form.condition_notes} onChange={(e) => set("condition_notes", e.target.value)} placeholder="e.g. Light scratch on lid, keyboard shine on WASD keys" className="mt-1 w-full resize-none p-2 text-sm" style={field} />
        </label>
      </section>

      <section>
        <Eyebrow>2 · Photos — every side and the serial number</Eyebrow>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {meta.photo_kinds.filter((k) => k.key !== "accessory").map((k) => (
            <PhotoSlot key={k.key} label={k.label} photos={photosOf(k.key)} required={meta.required_photo_kinds.includes(k.key)}
              editable={editable} busy={uploading === k.key} onAdd={(f) => addPhoto(k.key, f)} onDelete={deletePhoto} />
          ))}
        </div>
      </section>

      <section>
        <Eyebrow>3 · Accessories handed over</Eyebrow>
        <div className="mt-2 space-y-1.5">
          {form.accessories.map((a, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_28px] gap-2">
              <input disabled={!editable} value={a.name} onChange={(e) => set("accessories", form.accessories.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} placeholder="Item" className="p-1.5 text-sm" style={field} />
              <input disabled={!editable} value={a.serial || ""} onChange={(e) => set("accessories", form.accessories.map((x, j) => j === i ? { ...x, serial: e.target.value } : x))} placeholder="Serial (optional)" className="p-1.5 text-sm" style={{ ...field, fontFamily: F.mono }} />
              {editable && <button type="button" onClick={() => set("accessories", form.accessories.filter((_, j) => j !== i))}><Trash2 size={14} style={{ color: C.inkSoft }} /></button>}
            </div>
          ))}
          {!form.accessories.length && <p className="text-xs" style={{ color: C.inkSoft }}>No accessories — the device only.</p>}
        </div>
        {editable && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {QUICK_ACCESSORIES.filter((n) => !form.accessories.some((a) => a.name === n)).map((n) => (
              <button key={n} type="button" onClick={() => set("accessories", [...form.accessories, { name: n, serial: "" }])} className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink }}><Plus size={10} />{n}</button>
            ))}
            <button type="button" onClick={() => set("accessories", [...form.accessories, { name: "", serial: "" }])} className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" style={{ border: `1px dashed ${C.rule}`, color: C.inkSoft }}><Plus size={10} />Other</button>
          </div>
        )}
        {(form.accessories.length > 0 || photosOf("accessory").length > 0) && (
          <div className="mt-2 max-w-sm">
            <PhotoSlot label="Accessories photo" photos={photosOf("accessory")} required={form.accessories.length > 0}
              editable={editable} busy={uploading === "accessory"} onAdd={(f) => addPhoto("accessory", f)} onDelete={deletePhoto} />
          </div>
        )}
      </section>

      <section>
        <Eyebrow>4 · Warranty during the rental</Eyebrow>
        <label className="mt-2 flex items-center gap-2 text-sm" style={{ display: "flex", color: C.ink }}>
          <input type="checkbox" disabled={!editable} checked={form.warranty_included} onChange={(e) => set("warranty_included", e.target.checked)} />
          <ShieldCheck size={14} style={{ color: C.green }} /> This device is covered by our warranty during the rental
        </label>
        {form.warranty_included && (
          <div className="mt-2 space-y-2">
            <label className="block text-xs" style={{ display: "block", color: C.inkSoft }}>Covered for (months, max {data.tenure_months})
              <input type="number" min="1" max={data.tenure_months} disabled={!editable} value={form.warranty_months} onChange={(e) => set("warranty_months", e.target.value)} placeholder={`Whole tenure (${data.tenure_months})`} className="mt-1 block w-40 p-1.5 text-sm" style={{ ...field, fontFamily: F.mono }} />
            </label>
            <label className="block text-xs" style={{ display: "block", color: C.inkSoft }}>Warranty conditions (the customer approves exactly this text)
              <textarea rows={4} disabled={!editable} value={form.warranty_terms} onChange={(e) => set("warranty_terms", e.target.value)}
                placeholder={"e.g. Hardware faults not caused by misuse are repaired free, or the device is swapped within 48 hours.\nNot covered: physical damage, liquid damage, lost accessories, software installed by the customer."}
                className="mt-1 w-full resize-y p-2 text-sm" style={field} />
            </label>
          </div>
        )}
        {editable && allLineIds.length > 1 && (
          <button type="button" onClick={copyWarrantyToAll} className="mt-2 flex items-center gap-1 text-xs underline" style={{ color: C.inkSoft }}><Copy size={11} /> Use this warranty for every device in the agreement (save first)</button>
        )}
      </section>

      {note && <p className="text-xs" style={{ color: C.green }}>{note}</p>}
      <ErrorNote message={error} />
      {editable && (
        <button type="button" onClick={save} disabled={saving} className="w-full py-2.5 text-sm" style={{ backgroundColor: C.green, color: C.onAccent, fontWeight: 600, opacity: saving ? 0.6 : 1 }}>
          {saving ? "Saving…" : "Save condition, accessories & warranty"}
        </button>
      )}
    </div>
  );
}

/*
 * Device handover for a rental agreement: per device, the working-condition
 * check, photos of every side + serial label + accessories, the accessories
 * list and the shop's warranty. All of it goes to the customer for
 * approval; the approval link can't be sent until every device is complete.
 */
export default function DeviceHandoverModal({ rental, onClose, onChanged }) {
  const lines = rental.lines || [];
  const [active, setActive] = useState(lines[0]?.id);

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto p-4" style={{ backgroundColor: "rgba(4,9,18,0.72)" }} onClick={onClose}>
      <div className="my-6 w-full max-w-3xl p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <Eyebrow>Device handover & warranty</Eyebrow>
            <p className="mt-1 text-xs" style={{ color: C.inkSoft }}>
              {rental.agreement_code} · {rental.party_name} — everything here is shown to the customer for approval.
            </p>
          </div>
          <button type="button" onClick={onClose}><X size={17} /></button>
        </div>
        {lines.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {lines.map((l) => (
              <button key={l.id} type="button" onClick={() => setActive(l.id)} className="flex items-center gap-1.5 px-2.5 py-1 text-xs"
                style={{ border: `1px solid ${active === l.id ? C.stamp : C.rule}`, color: active === l.id ? C.stamp : C.ink, fontWeight: 600 }}>
                {l.handover_issues?.length ? <ImagePlus size={11} style={{ color: C.amber }} /> : <CheckCircle2 size={11} style={{ color: C.green }} />}
                {l.asset?.asset_tag} · {l.description}
              </button>
            ))}
          </div>
        )}
        <div className="mt-4">
          {active ? <DeviceHandover key={active} lineId={active} allLineIds={lines.map((l) => l.id)} onSaved={onChanged} /> : <p className="text-sm">This agreement has no devices.</p>}
        </div>
      </div>
    </div>
  );
}
