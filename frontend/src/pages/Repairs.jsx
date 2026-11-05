import { useCallback, useEffect, useState } from "react";
import {
  BarChart3, Check, Cpu, IndianRupee, LayoutGrid, List, MapPinned, MessageCircle, PackageCheck, Plus,
  Terminal, Truck, UserCheck, Wrench, X,
} from "lucide-react";
import { C, F, money, todayISO } from "../lib/theme";
import { api } from "../lib/api";
import { onStoreChanged } from "../lib/storeEvents";
import { useSession } from "../context/SessionContext";
import { Locked, Pill, PillButton, Spinner, ErrorNote, Eyebrow, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import EstimateApprovalPanel from "../components/repairs/EstimateApprovalPanel";
import ApprovalLinkCard from "../components/repairs/ApprovalLinkCard";
import PortalLinkButton from "../components/repairs/PortalLinkButton";
import { PartyChatModal } from "../components/PartyThread";
import RevisionPanel from "../components/repairs/RevisionPanel";
import DiagnosisPanel from "../components/repairs/DiagnosisPanel";
import StaffPerformance from "../components/repairs/StaffPerformance";
import ManualLines from "../components/repairs/ManualLines";
import { blankLine, linesTotal, pricingPayload, validatePricing } from "../components/repairs/bookingModel";
import { isAdminLevel } from "../lib/accessLevel";

const STAGES = ["Received", "Diagnosing", "In progress", "Ready for pickup", "Delivered"];
const STAGE_COLOR = { Received: C.blue, Diagnosing: C.amber, "In progress": C.stamp, "Ready for pickup": C.green, Delivered: C.inkSoft };

function StageStepper({ status }) {
  const idx = STAGES.indexOf(status);
  return (
    <div className="flex items-center">
      {STAGES.map((s, i) => (
        <div key={s} className="flex flex-1 items-center last:flex-none">
          <div className="flex flex-col items-center gap-1">
            <div className="flex h-6 w-6 items-center justify-center" style={{ borderRadius: 999, backgroundColor: i <= idx ? STAGE_COLOR[status] : C.slip2, border: `1px solid ${i <= idx ? STAGE_COLOR[status] : C.rule}` }}>
              {i < idx ? <Check size={13} style={{ color: C.onAccent }} /> : <span className="text-xs" style={{ fontFamily: F.mono, color: i <= idx ? C.onAccent : C.inkSoft }}>{i + 1}</span>}
            </div>
            <span className="text-center text-xs" style={{ fontFamily: F.body, color: i <= idx ? C.ink : C.inkSoft, maxWidth: 74 }}>{s}</span>
          </div>
          {i < STAGES.length - 1 && <div className="mx-1 h-px flex-1" style={{ backgroundColor: i < idx ? STAGE_COLOR[status] : C.rule }} />}
        </div>
      ))}
    </div>
  );
}

function ServiceChecklist({ services, stockPointSlug, brand, selected, onToggle }) {
  const segments = ["Hardware", "Software"];
  return (
    <div className="space-y-4">
      {segments.map((seg) => (
        <div key={seg}>
          <p className="flex items-center gap-1.5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: C.inkSoft }}>
            {seg === "Hardware" ? <Cpu size={12} /> : <Terminal size={12} />} {seg} issue
          </p>
          <div className="mt-2 space-y-1.5">
            {services.filter((s) => s.segment === seg).map((s) => {
              const on = selected.includes(s.id);
              const part = s.part;
              const stockRow = part?.stock.find((st) => st.stock_point === stockPointSlug);
              const stockHere = stockRow ? stockRow.quantity : null;
              const elsewhere = part && stockHere === 0 ? part.stock.filter((st) => st.stock_point !== stockPointSlug && st.quantity > 0) : [];
              const compatIssue = part && brand !== "Apple" && !part.compatible_brands.includes(brand);
              return (
                <div key={s.id} data-panel className="px-3 py-2" style={{ border: `1px solid ${on ? C.stamp : C.rule}`, backgroundColor: on ? `${C.stamp}14` : C.slip2 }}>
                  <button onClick={() => onToggle(s.id)} className="flex w-full items-center justify-between text-left">
                    <span className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, color: C.ink }}>
                      <span className="flex h-4 w-4 items-center justify-center" style={{ border: `1px solid ${on ? C.stamp : C.rule}`, backgroundColor: on ? C.stamp : "transparent" }}>{on && <Check size={11} style={{ color: C.onAccent }} />}</span>
                      {s.label}
                    </span>
                    <span className="text-sm" style={{ fontFamily: F.mono, color: C.inkSoft }}>{money(s.charge)}</span>
                  </button>
                  {on && part && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 pl-6 text-xs" style={{ fontFamily: F.body }}>
                      <span style={{ color: C.inkSoft }}>{part.name}</span>
                      {brand === "Apple" ? (
                        <Pill color={C.amber}>Sourced from authorised Apple vendor</Pill>
                      ) : compatIssue ? (
                        <Pill color={C.carbon}>Not listed for {brand}</Pill>
                      ) : stockHere > 0 ? (
                        <Pill color={C.green}>{stockHere} in stock here</Pill>
                      ) : (
                        <Pill color={C.carbon}>Out of stock here{elsewhere.length ? ` — try ${elsewhere.map((e) => e.stock_point).join(", ")}` : ""}</Pill>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function QuickAddParty({ onClose, onAdded }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("Retail");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [city, setCity] = useState("");
  const [classification, setClassification] = useState("individual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!name.trim()) return setError("Name is required.");
    const phoneDigits = phone.replace(/\D/g, "");
    if (phoneDigits.length < 10 || phoneDigits.length > 15) return setError("Enter a valid phone number with 10 to 15 digits.");
    if (!email.trim()) return setError("Email is required.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return setError("Enter a valid email address.");
    if (!city.trim()) return setError("City is required.");
    setBusy(true);
    setError("");
    try {
      const party = await api.post("/parties/", {
        name: name.trim(), type, customer_classification: classification, phone: phone.trim(), email: email.trim(), city: city.trim(),
        joined: todayISO(),
      });
      onAdded(party);
    } catch (e) {
      const body = e.body || {};
      const fields = Object.entries(body).filter(([k]) => k !== "detail").map(([k, v]) => `${k.replace(/_/g, " ")}: ${[].concat(v).join(" ")}`);
      setError(body.detail || fields.join(" · ") || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 p-3" data-panel style={{ border: `1px solid ${C.stamp}`, backgroundColor: `${C.stamp}0A` }}>
      <div className="flex items-center justify-between">
        <Eyebrow>New customer</Eyebrow>
        <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={14} style={{ color: C.inkSoft }} /></button>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name *" className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        <select value={type} onChange={(e) => setType(e.target.value)} className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
          <option>Retail</option><option>Dealer</option><option>Rental</option>
        </select>
        <select value={classification} onChange={(event) => setClassification(event.target.value)} className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
          <option value="individual">Individual</option><option value="business">Business / Corporate</option><option value="dealer">Dealer</option>
        </select>
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Phone number *" className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="Email *" className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="City *" className="bg-transparent px-2 py-1.5 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
      </div>
      <ErrorNote message={error} />
      <button onClick={submit} disabled={busy} className="mt-2 flex w-full items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", opacity: busy ? 0.7 : 1 }}>
        <Plus size={12} /> {busy ? "Adding\u2026" : "Add & select this customer"}
      </button>
    </div>
  );
}

function NewTicketModal({ parties, services, stockPoints, onClose, onCreate }) {
  const { can } = useSession();
  const canPrice = can("repairs.approve");
  const blankDevice = () => ({ brand: "Dell", model_name: "", serial: "", issue: "", lines: [blankLine()], advance: "" });
  const [entryType, setEntryType] = useState("single");
  const [localParties, setLocalParties] = useState(parties);
  const [party, setParty] = useState(parties[0]?.id);
  const [addingParty, setAddingParty] = useState(false);
  const [brand, setBrand] = useState("Dell");
  const [model, setModel] = useState("");
  const [serial, setSerial] = useState("");
  const [stockPointId, setStockPointId] = useState(stockPoints.find((s) => s.kind === "shop")?.id);
  const [issue, setIssue] = useState("");
  const [lines, setLines] = useState([blankLine()]);
  const [advanceInput, setAdvanceInput] = useState("");
  const [payment, setPayment] = useState("advance");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bulkDevices, setBulkDevices] = useState([blankDevice(), blankDevice()]);

  const stockPoint = stockPoints.find((s) => s.id === stockPointId);
  const total = entryType === "bulk" ? bulkDevices.reduce((sum, d) => sum + linesTotal(d.lines), 0) : linesTotal(lines);
  const updateBulkDevice = (index, patch) => setBulkDevices((current) => current.map((device, deviceIndex) => deviceIndex === index ? { ...device, ...patch } : device));

  const submit = async () => {
    if (entryType === "single" && (!model.trim() || !serial.trim() || !issue.trim())) return setError("Model, serial / asset tag and the reported issue are required.");
    if (entryType === "bulk" && bulkDevices.some((device) => !device.model_name.trim() || !device.serial.trim() || !device.issue.trim())) return setError("Every bulk device needs model, serial / asset tag and issue.");
    const problems = entryType === "bulk"
      ? bulkDevices.map((d) => validatePricing({ lines: d.lines, payment, advance: d.advance, needLines: canPrice })).find(Boolean)
      : validatePricing({ lines, payment, advance: advanceInput, needLines: canPrice });
    if (problems) return setError(problems);
    setBusy(true);
    setError("");
    try {
      if (entryType === "bulk") {
        await onCreate({
          party, stock_point: stockPointId, payment,
          received: todayISO(),
          devices: bulkDevices.map(({ lines: l, advance, ...device }) => ({ ...device, model_name: device.model_name.trim(), serial: device.serial.trim(), issue: device.issue.trim(), ...pricingPayload({ lines: l, payment, advance, canPrice }) })),
        }, true);
        return;
      }
      await onCreate({
        party, brand, model_name: model.trim(), serial: serial.trim() || "—",
        stock_point: stockPointId, issue: issue.trim() || "Not specified",
        payment, ...pricingPayload({ lines, payment, advance: advanceInput, canPrice }),
        received: todayISO(),
      }, false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between"><Eyebrow>New repair ticket</Eyebrow><button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button></div>

        <div className="mt-4 grid grid-cols-2" style={{ border: `1px solid ${C.rule}` }}>
          {[["single", "Single · 1 device"], ["bulk", "Bulk · 2+ devices"]].map(([value, label]) => <button key={value} type="button" onClick={() => setEntryType(value)} className="py-2 text-xs uppercase" style={{ backgroundColor: entryType === value ? C.stamp : "transparent", color: entryType === value ? C.onAccent : C.inkSoft, fontWeight: 600 }}>{label}</button>)}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Customer
            <select value={party} onChange={(e) => setParty(+e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {localParties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {!addingParty ? (
              <button type="button" onClick={() => setAddingParty(true)} className="mt-1 flex items-center gap-1 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>
                <Plus size={11} /> Customer not in the list? Add new
              </button>
            ) : (
              <QuickAddParty onClose={() => setAddingParty(false)} onAdded={(p) => { setLocalParties((l) => [p, ...l]); setParty(p.id); setAddingParty(false); }} />
            )}
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Drop-off shop
            <select value={stockPointId} onChange={(e) => setStockPointId(+e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {stockPoints.filter((s) => s.kind === "shop").map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          {entryType === "single" && <><label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Brand
            <select value={brand} onChange={(e) => setBrand(e.target.value)} className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              {["Dell", "HP", "Lenovo", "Asus", "Acer", "Apple", "MSI"].map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label className="block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Model
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. Latitude 5420" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
          </label>
          <label className="block text-xs sm:col-span-2" style={{ fontFamily: F.body, color: C.inkSoft }}>Serial / asset tag
            <input value={serial} onChange={(e) => setSerial(e.target.value)} placeholder="Required" className="mt-1 w-full bg-transparent py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
          </label>
          </>}
        </div>

        {entryType === "single" && <><label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Reported issue
          <textarea value={issue} onChange={(e) => setIssue(e.target.value)} rows={2} className="mt-1 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        {canPrice ? <>
          <p className="mt-4 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>Agreed work &amp; price</p>
          <div className="mt-2"><ManualLines lines={lines} onChange={setLines} /></div>
        </> : <p className="mt-4 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>The Admin sets the price and sends the customer's approval link.</p>}
        </>}

        {entryType === "bulk" && <div className="mt-4 space-y-4">
          {bulkDevices.map((device, index) => <section key={index} className="p-4" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
            <div className="flex items-center justify-between"><Eyebrow>Device {index + 1}</Eyebrow>{bulkDevices.length > 2 && <button type="button" onClick={() => setBulkDevices((current) => current.filter((_, deviceIndex) => deviceIndex !== index))}><X size={14} /></button>}</div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <select value={device.brand} onChange={(event) => updateBulkDevice(index, { brand: event.target.value })} className="bg-transparent px-2 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }}>{["Dell", "HP", "Lenovo", "Asus", "Acer", "Apple", "MSI"].map((item) => <option key={item}>{item}</option>)}</select>
              <input value={device.model_name} onChange={(event) => updateBulkDevice(index, { model_name: event.target.value })} placeholder="Model · required" className="bg-transparent px-2 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />
              <input value={device.serial} onChange={(event) => updateBulkDevice(index, { serial: event.target.value })} placeholder="Serial / asset tag · required" className="bg-transparent px-2 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />
            </div>
            <textarea value={device.issue} onChange={(event) => updateBulkDevice(index, { issue: event.target.value })} placeholder="Reported issue · required" rows={2} className="mt-2 w-full bg-transparent px-2 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />
            {canPrice && <div className="mt-3"><ManualLines lines={device.lines} onChange={(l) => updateBulkDevice(index, { lines: l })} /></div>}
            {payment === "advance" && <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Advance for this device (₹)
              <input type="number" min="0" value={device.advance} onChange={(e) => updateBulkDevice(index, { advance: e.target.value })} placeholder="0 = none" className="mt-1 w-full bg-transparent px-2 py-1.5 text-sm" style={{ border: `1px solid ${C.rule}` }} />
            </label>}
          </section>)}
          <button type="button" onClick={() => setBulkDevices((current) => [...current, blankDevice()])} className="flex w-full items-center justify-center gap-1 py-2 text-xs uppercase" style={{ border: `1px dashed ${C.stamp}`, color: C.stamp }}><Plus size={13} /> Add another device</button>
        </div>}

        <div className="mt-4 flex overflow-hidden rounded-xl" style={{ border: `1px solid ${C.rule}` }}>
          {[["advance", "Take an advance"], ["full", "Pay on delivery"]].map(([k, label]) => (
            <button key={k} onClick={() => setPayment(k)} className="flex-1 py-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: payment === k ? C.onAccent : C.inkSoft, backgroundColor: payment === k ? C.stamp : "transparent" }}>{label}</button>
          ))}
        </div>

        {payment === "advance" && entryType === "single" && (
          <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Advance (₹) — typed in, leave blank for none
            <input type="number" min="0" value={advanceInput} onChange={(e) => setAdvanceInput(e.target.value)} placeholder="e.g. 1000" className="mt-1 w-full bg-transparent px-3 py-2 text-sm" style={{ border: `1px solid ${C.rule}` }} />
          </label>
        )}

        {canPrice && <div className="mt-3 flex items-center justify-between px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Estimate total</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(total)}</span>
        </div>}

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <Wrench size={13} /> {busy ? "Creating…" : entryType === "bulk" ? `Create bulk order · ${bulkDevices.length} tickets` : "Create single repair ticket"}
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Reopen -- the device came back. Every service is checked against
 *  what this ticket was ORIGINALLY serviced for: same service + an
 *  active repair warranty suggests free; anything new (or without an
 *  active warranty) suggests full price. Staff can override any line.
 * ------------------------------------------------------------------ */
function ReopenModal({ ticket, services, onClose, onReopened }) {
  const [issue, setIssue] = useState("");
  const [selected, setSelected] = useState({}); // { [serviceId]: { checked, charge, touched } }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const originalServiceIds = new Set(ticket.services.map((s) => s.id));

  const toggle = (service) => {
    setSelected((cur) => {
      const isOn = cur[service.id]?.checked;
      if (isOn) {
        const next = { ...cur };
        delete next[service.id];
        return next;
      }
      const recurrence = originalServiceIds.has(service.id);
      const covered = ticket.warranty_active && recurrence;
      // `touched: false` -- this is only the suggested price for display.
      // The actual charge applied comes from the backend's own live
      // warranty check unless staff explicitly edits the amount below.
      return { ...cur, [service.id]: { checked: true, charge: covered ? 0 : service.charge, covered, recurrence, touched: false } };
    });
  };

  const setCharge = (id, value) => setSelected((cur) => ({ ...cur, [id]: { ...cur[id], charge: value, touched: true } }));

  const chosen = Object.entries(selected).filter(([, v]) => v.checked);
  const total = chosen.reduce((s, [, v]) => s + (+v.charge || 0), 0);

  const submit = async () => {
    if (!issue.trim()) return setError("Describe what the customer is reporting.");
    if (!chosen.length) return setError("Select at least one service for this visit.");
    setBusy(true);
    setError("");
    try {
      const t = await api.post(`/tickets/${ticket.id}/reopen/`, {
        issue: issue.trim(),
        // only send override_charge for lines staff actually edited --
        // everything else is decided by the backend's own live warranty
        // check at the moment of submission, not whatever this screen
        // happened to compute when it first loaded
        items: chosen.map(([id, v]) => (
          v.touched ? { service: +id, override_charge: +v.charge || 0 } : { service: +id }
        )),
      });
      onReopened(t);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between">
          <Eyebrow>Reopen ticket -- device came back</Eyebrow>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>

        {ticket.warranty_active ? (
          <div className="mt-3 flex items-center gap-2 px-3 py-2" style={{ backgroundColor: `${C.green}14`, border: `1px solid ${C.green}` }}>
            <PackageCheck size={13} style={{ color: C.green }} />
            <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>Active repair warranty until {ticket.warranty_end_date} -- a recurrence of an originally-repaired service will suggest \u20b90.</span>
          </div>
        ) : (
          <div className="mt-3 flex items-center gap-2 px-3 py-2" style={{ backgroundColor: `${C.amber}14`, border: `1px solid ${C.amber}` }}>
            <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>No active repair warranty on this ticket -- all services will be charged at full price.</span>
          </div>
        )}

        <label className="mt-3 block text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>What is the customer reporting this time?
          <textarea value={issue} onChange={(e) => setIssue(e.target.value)} rows={2} className="mt-1 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </label>

        <p className="mt-4 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>Services needed this visit</p>
        <div className="mt-2 space-y-1.5">
          {services.map((s) => {
            const on = !!selected[s.id]?.checked;
            const recurrence = originalServiceIds.has(s.id);
            return (
              <div key={s.id} data-panel className="px-3 py-2" style={{ border: `1px solid ${on ? C.stamp : C.rule}`, backgroundColor: on ? `${C.stamp}14` : C.slip2 }}>
                <button onClick={() => toggle(s)} className="flex w-full items-center justify-between text-left">
                  <span className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, color: C.ink }}>
                    <span className="flex h-4 w-4 items-center justify-center" style={{ border: `1px solid ${on ? C.stamp : C.rule}`, backgroundColor: on ? C.stamp : "transparent" }}>{on && <Check size={11} style={{ color: C.onAccent }} />}</span>
                    {s.label}
                    {recurrence && <Pill color={C.blue}>done before on this ticket</Pill>}
                  </span>
                  <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>list price {money(s.charge)}</span>
                </button>
                {on && (
                  <div className="mt-2 flex items-center gap-2 pl-6">
                    <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Charge this visit:</span>
                    <input value={selected[s.id].charge} onChange={(e) => setCharge(s.id, e.target.value.replace(/\D/g, ""))} className="w-24 bg-transparent px-2 py-1 text-xs outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
                    {selected[s.id].touched ? (
                      <Pill color={C.amber}>you set this</Pill>
                    ) : selected[s.id].covered ? (
                      <Pill color={C.green}>auto \u2014 free, warranty</Pill>
                    ) : (
                      <Pill color={C.inkSoft}>auto \u2014 full price</Pill>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex items-center justify-between px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Total for this visit</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(total)}</span>
        </div>

        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <Truck size={13} /> {busy ? "Reopening\u2026" : "Reopen & notify customer"}
        </button>
      </div>
    </div>
  );
}

/* A repair job's invoice as seen from the Repairs module: raised here,
 * paid in Sales & Invoices, so only its status is shown. */
function RepairInvoiceRow({ label, invoice }) {
  if (invoice.status === "Refunded" || invoice.status === "Cancelled") {
    return (
      <div className="mt-2 flex items-center justify-between px-3 py-2.5" style={{ border: `1px solid ${C.rule}` }}>
        <span className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}><PackageCheck size={14} />{label}</span>
        <Pill color={C.inkSoft}>{invoice.status}</Pill>
      </div>
    );
  }
  const paid = invoice.status === "Paid";
  const color = paid ? C.green : C.amber;
  return (
    <div className="mt-2 flex items-center justify-between px-3 py-2.5" style={{ backgroundColor: `${color}17`, border: `1px solid ${color}` }}>
      <span className="flex items-center gap-1.5 text-sm" style={{ fontFamily: F.body, color: C.ink }}><PackageCheck size={14} style={{ color }} />{label}</span>
      <Pill color={color}>{paid ? (invoice.pay_method === "No charge" ? "No charge" : "Paid") : invoice.status === "Overdue" ? "Overdue" : "Awaiting payment"}</Pill>
    </div>
  );
}

/* Who is working this ticket. The Super Admin can give it to staff of any
 * store, an Admin to staff of their own store; either can take it over when
 * the assigned person is away. */
function AssignPanel({ ticket, meId, canAssign, isOwner, onChanged }) {
  const [staff, setStaff] = useState(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const delivered = ticket.status === "Delivered";

  const send = async (assigned_to) => {
    setBusy(true);
    setError("");
    try {
      onChanged(await api.post(`/tickets/${ticket.id}/assign/`, { assigned_to }));
      setChoice("");
    } catch (e) {
      setError(e.body?.assigned_to ? [].concat(e.body.assigned_to).join(" ") : e.body?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (canAssign && !delivered) api.get("/tickets/staff/").then(setStaff).catch(() => setStaff([]));
  }, [canAssign, delivered]);

  const mine = ticket.assigned_to === meId;
  return (
    <div className="mt-4 p-3" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex items-center justify-between gap-2">
        <Eyebrow>Assigned to</Eyebrow>
        {ticket.assigned_to ? <Pill color={mine ? C.green : C.stamp}>{mine ? "You" : ticket.assigned_to_name}</Pill> : <Pill color={C.inkSoft}>Unassigned</Pill>}
      </div>
      <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
        {ticket.assigned_to
          ? `${ticket.assigned_to_name}${ticket.assigned_to_store ? ` · ${ticket.assigned_to_store}` : ""} works this job.${canAssign || mine ? "" : " Only they or an Admin can move it forward."}`
          : "Not given to anyone yet. This job can't move on until it is assigned."}
      </p>
      {canAssign && !delivered && (
        <div className="mt-2">
          <div className="flex flex-wrap gap-2">
            <select value={choice} onChange={(e) => { setChoice(e.target.value); setError(""); }} aria-label="Staff member" className="min-w-0 flex-1 bg-transparent px-2.5 py-1.5 text-sm outline-none" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontFamily: F.body }}>
              <option value="">{staff && !staff.length ? "No staff available" : "Choose staff…"}</option>
              {(staff || []).filter((u) => u.id !== ticket.assigned_to).map((u) => <option key={u.id} value={u.id}>{u.name} — {u.stock_point_name}</option>)}
            </select>
            <button type="button" disabled={!choice || busy} onClick={() => send(Number(choice))} className="px-3 py-1.5 text-xs uppercase disabled:opacity-50" style={{ backgroundColor: C.orange, color: C.onAccent, fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em" }}>{ticket.assigned_to ? "Reassign" : "Assign"}</button>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {!mine && !isOwner && <button type="button" disabled={busy} onClick={() => send(meId)} className="flex items-center gap-1 px-3 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink, fontWeight: 700 }}><UserCheck size={12} /> {ticket.assigned_to ? "Take over this job" : "Take it myself"}</button>}
            {ticket.assigned_to && <button type="button" disabled={busy} onClick={() => send(null)} className="px-3 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.inkSoft }}>Unassign</button>}
          </div>
        </div>
      )}
      <ErrorNote message={error} />
    </div>
  );
}

function TicketDetail({ ticketId, onClose, onChanged }) {
  const { can, me } = useSession();
  const [ticket, setTicket] = useState(null);
  const [services, setServices] = useState([]);
  const [reopening, setReopening] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideError, setOverrideError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);

  const load = useCallback(() => api.get(`/tickets/${ticketId}/`).then(setTicket), [ticketId]);
  useEffect(() => { load(); api.getAll("/services/").then(setServices); }, [load]);
  if (!ticket) return null;

  // a job given to someone else is theirs to move forward; an Admin / Super Admin can always step in
  const locked = !!ticket.assigned_to && ticket.assigned_to !== me?.id && !can("repairs.assign");
  const canWork = can("repairs.manage") && !locked;
  const delivered = ticket.status === "Delivered";
  const nextStage = STAGES[STAGES.indexOf(ticket.status) + 1];
  const activeReopen = ticket.reopens.find((r) => !r.invoice);
  const settledReopens = ticket.reopens.filter((r) => r.invoice);

  const advance = async () => { const t = await api.post(`/tickets/${ticket.id}/advance/`); setTicket(t); onChanged(t); };
  const startAnyway = async () => {
    setOverrideError("");
    try { const t = await api.post(`/tickets/${ticket.id}/advance/`, { override_reason: overrideReason.trim() }); setTicket(t); onChanged(t); setOverrideReason(""); }
    catch (e) { setOverrideError(e.body?.detail || e.message); }
  };
  const settle = async () => { const t = await api.post(`/tickets/${ticket.id}/settle/`); setTicket(t); onChanged(t); };

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, color: C.ink }}>{ticket.code}</p>
              {ticket.repair_type === "bulk" && <Pill color={C.blue}>Bulk · {ticket.order_code}</Pill>}
              {ticket.warranty_active && <Pill color={C.green}>warranty until {ticket.warranty_end_date}</Pill>}
            </div>
            <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{ticket.party_name} · {ticket.brand} {ticket.model_name} · {ticket.serial}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-black/5"><X size={18} style={{ color: C.inkSoft }} /></button>
        </div>

        <div className="mt-5"><StageStepper status={ticket.status} /></div>

        <AssignPanel ticket={ticket} meId={me?.id} isOwner={!!(me?.is_superuser || me?.role_slug === "owner")} canAssign={can("repairs.assign")} onChanged={(t) => { setTicket(t); onChanged(t); }} />

        <div className="mt-5 p-3" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
          <Eyebrow>Reported issue</Eyebrow>
          <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.ink }}>{ticket.issue}</p>
        </div>

        <EstimateApprovalPanel
          key={`${ticket.id}-${ticket.current_estimate?.id || "new"}`}
          ticket={ticket}
          services={services}
          canManage={canWork}
          canApprove={can("repairs.approve")}
          onChanged={(updated) => { setTicket(updated); onChanged(updated); }}
        />

        <DiagnosisPanel
          key={`diag-${ticket.id}-${ticket.diagnosed_at || 0}`}
          ticket={ticket}
          canWork={canWork && ticket.assigned_to === me?.id}
          canApprove={can("repairs.approve")}
          onChanged={(updated) => { setTicket(updated); onChanged(updated); }}
        />

        <RevisionPanel
          key={`rev-${ticket.id}-${ticket.pending_revision?.id || 0}-${ticket.current_estimate?.id || 0}`}
          ticket={ticket}
          services={services}
          canWork={canWork}
          canApprove={can("repairs.approve")}
          onChanged={(updated) => { setTicket(updated); onChanged(updated); }}
        />

        {activeReopen && (
          <div className="mt-3 p-3" data-panel style={{ border: `1px solid ${C.amber}`, backgroundColor: `${C.amber}0A` }}>
            <Eyebrow>Follow-up visit in progress</Eyebrow>
            <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.ink }}>{activeReopen.issue}</p>
            <div className="mt-2 space-y-1">
              {activeReopen.items.map((it) => (
                <div key={it.id} className="flex items-center justify-between text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  <span>{it.service_label}{it.covered_by_warranty && <Pill color={C.green}>warranty</Pill>}</span>
                  <span style={{ fontFamily: F.mono, color: C.ink }}>{money(it.charge)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="mt-5 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>Original work order</p>
        <div className="mt-2 space-y-1.5">
          {ticket.services.map((s) => (
            <div key={s.id} className="flex items-center justify-between px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
              <span className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, color: C.ink }}>{s.label}{s.part && <span style={{ fontFamily: F.mono, color: C.inkSoft, fontSize: 11 }}>· {s.part.name}</span>}</span>
              <span className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{money(s.charge)}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between px-3 py-2" data-panel style={{ border: `1px solid ${C.rule}` }}>
          <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Original total</span>
          <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{money(ticket.total)}</span>
        </div>

        {ticket.advance_invoice && (
          <>
            <RepairInvoiceRow label={`Advance · ${ticket.advance_invoice.code} · ${money(ticket.advance_invoice.amount)}`} invoice={ticket.advance_invoice} />
            {ticket.advance_invoice.status === "Paid" ? (
              <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{money(ticket.advance_paid)} received — it's deducted from the final bill.</p>
            ) : ["Payment link sent", "Overdue"].includes(ticket.advance_invoice.status) && (
              <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                Collect the advance in Sales &amp; Invoices before work starts. Not paid by pickup? It's added to the final bill instead.
              </p>
            )}
          </>
        )}

        {ticket.status === "Delivered" ? (
          <>
            {ticket.invoice && <RepairInvoiceRow label={`${ticket.invoice.code} · ${ticket.invoice.stock_point_name}`} invoice={ticket.invoice} />}
            {settledReopens.map((r) => (
              <RepairInvoiceRow key={r.id} label={`Follow-up · ${r.invoice.code} · ${money(r.invoice.amount)}`} invoice={r.invoice} />
            ))}
            {[ticket.invoice, ...settledReopens.map((r) => r.invoice)].some((inv) => inv && inv.status !== "Paid") && (
              <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                Payment is collected in Sales &amp; Invoices — record it or send a UPI link there.
              </p>
            )}
            {canWork && can("repairs.book") && ticket.can_reopen && (
              <button onClick={async () => { setTicket(await api.get(`/tickets/${ticket.id}/`)); setReopening(true); }} className="mt-3 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.amber, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
                <Truck size={13} /> Device came back -- reopen ticket
              </button>
            )}
          </>
        ) : (
          <>
            {ticket.pending_invoice && (
              <>
                <RepairInvoiceRow label={`${ticket.pending_invoice.code} · ${money(ticket.pending_invoice.amount)}`} invoice={ticket.pending_invoice} />
                <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
                  Waiting for payment — record it or send a UPI link in Sales &amp; Invoices. The ticket is marked Delivered automatically once it's paid.
                </p>
              </>
            )}
            {canWork && nextStage === "In progress" && ticket.awaiting_diagnosis && (
              <div className="mt-4 p-3" style={{ border: `1px dashed ${C.amber}`, backgroundColor: `${C.amber}0D` }}>
                <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>Work can't start yet — waiting for {ticket.assigned_to_name}'s diagnosis.</p>
                {can("repairs.assign") && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <input value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} placeholder="Reason to start anyway" className="min-w-0 flex-1 px-2 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}` }} aria-label="Reason to start without the diagnosis" />
                    <button type="button" disabled={!overrideReason.trim()} onClick={startAnyway} className="px-3 py-1.5 text-xs uppercase disabled:opacity-50" style={{ border: `1px solid ${C.stamp}`, color: C.stamp, fontWeight: 600 }}>Start anyway</button>
                  </div>
                )}
                {overrideError && <p className="mt-1 text-xs" style={{ color: C.carbon }}>{overrideError}</p>}
              </div>
            )}
            {canWork && !ticket.assigned_to && (
              <p className="mt-4 p-3 text-xs" style={{ fontFamily: F.body, color: C.ink, border: `1px dashed ${C.amber}`, backgroundColor: `${C.amber}0D` }}>
                Assign this job to a staff member first. It can't move on until then.
              </p>
            )}
            {canWork && ticket.assigned_to && nextStage && nextStage !== "Delivered" && !ticket.pending_invoice && !(nextStage === "In progress" && ticket.awaiting_diagnosis) && (
              <button onClick={advance} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
                <Truck size={13} /> {can("repairs.book") ? `Move to "${nextStage}" & notify customer` : nextStage === "Ready for pickup" ? "Job done — send back to Admin" : `Move to "${nextStage}"`}
              </button>
            )}
            {ticket.status === "Ready for pickup" && canWork && can("repairs.book") && !ticket.pending_invoice && (
              <button onClick={settle} className="mt-2 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
                <IndianRupee size={13} /> Raise invoice — delivered once paid
              </button>
            )}
          </>
        )}

        {can("portal.manage") && !delivered && <PortalLinkButton partyId={ticket.party} partyName={ticket.party_name} />}
        {can("parties.view") && (
          <button type="button" onClick={() => setChatOpen(true)} className="mt-2 flex w-full items-center justify-center gap-1.5 py-2 text-xs" style={{ border: `1px solid ${C.rule}`, color: C.ink }}>
            <MessageCircle size={13} style={{ color: C.green }} /> Chat on WhatsApp
          </button>
        )}
        {chatOpen && <PartyChatModal partyId={ticket.party} partyName={ticket.party_name} onClose={() => setChatOpen(false)} />}

        <p className="mt-6 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>Customer notifications</p>
        <div className="mt-2 space-y-2">
          {ticket.notifications.map((n) => (
            <div key={n.id} className="px-3 py-2 rounded-xl" style={{ backgroundColor: C.slip2 }}>
              <p className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{n.text}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{n.channel} · {new Date(n.at).toLocaleString()}</p>
            </div>
          ))}
        </div>

        {reopening && (
          <ReopenModal ticket={ticket} services={services} onClose={() => setReopening(false)}
            onReopened={(t) => { setTicket(t); onChanged(t); setReopening(false); }} />
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Kanban board -- drag-and-drop stage moves. Native HTML5 drag
 *  events, no extra dependency. Optimistic UI: the card jumps to the
 *  new column immediately, and rolls back if the API call fails.
 *  "Delivered" is never a plain set-stage move -- dropping there
 *  triggers the real settle flow (generates the invoice), and is only
 *  a valid drop target from "Ready for pickup".
 * ------------------------------------------------------------------ */
function KanbanCard({ ticket, draggable, onDragStart, onClick }) {
  return (
    <div
      draggable={draggable}
      onDragStart={draggable ? onDragStart : undefined}
      onClick={onClick}
      data-panel
      className="cursor-pointer px-3 py-2.5"
      style={{ border: `1px solid ${C.rule}`, borderLeft: `3px solid ${STAGE_COLOR[ticket.status]}`, backgroundColor: C.slip, opacity: draggable ? 1 : 0.85 }}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{ticket.code}</span>
        <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{money(ticket.total)}</span>
      </div>
      <p className="mt-1 truncate text-xs" style={{ fontFamily: F.body, color: C.ink }}>{ticket.party_name}</p>
      <p className="truncate text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{ticket.brand} {ticket.model_name}</p>
      <p className="mt-1 flex items-center gap-1 truncate text-[11px]" style={{ fontFamily: F.body, color: ticket.assigned_to ? C.stamp : C.inkSoft }}><UserCheck size={11} />{ticket.assigned_to ? ticket.assigned_to_name : "Unassigned"}</p>
    </div>
  );
}

function KanbanBoard({ tickets, canManage, meId, canAssign, onOpen, onMoved, onError }) {
  const mayMove = (t) => canManage && (!t.assigned_to || t.assigned_to === meId || canAssign);
  const [dragTicket, setDragTicket] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const byStage = STAGES.reduce((acc, s) => { acc[s] = tickets.filter((t) => t.status === s); return acc; }, {});

  const handleDrop = async (targetStage) => {
    setDragOverCol(null);
    const ticket = dragTicket;
    setDragTicket(null);
    if (!ticket || ticket.status === targetStage) return;
    if (!mayMove(ticket)) { onError(`This job is assigned to ${ticket.assigned_to_name}. Ask an Admin to take it over or reassign it.`); return; }

    if (targetStage === "Delivered") {
      if (ticket.status !== "Ready for pickup") {
        onError("Only tickets that are Ready for pickup can be dropped into Delivered -- it raises the invoice.");
        return;
      }
      // Not optimistic: raising the invoice doesn't deliver the ticket --
      // it stays Ready for pickup until the invoice is paid.
      const previous = ticket;
      setBusyId(ticket.id);
      try {
        const updated = await api.post(`/tickets/${ticket.id}/settle/`);
        onMoved(updated);
        if (updated.pending_invoice) {
          onError(`Invoice ${updated.pending_invoice.code} raised. ${ticket.code} moves to Delivered once it's paid in Sales & Invoices.`);
        }
      } catch (e) {
        onMoved(previous); // roll back
        onError(e.body?.detail || e.message);
      } finally {
        setBusyId(null);
      }
      return;
    }

    const previous = ticket;
    onMoved({ ...ticket, status: targetStage }); // optimistic
    setBusyId(ticket.id);
    try {
      const updated = await api.post(`/tickets/${ticket.id}/set-stage/`, { status: targetStage });
      onMoved(updated);
    } catch (e) {
      onMoved(previous); // roll back
      onError(e.body?.detail || e.message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-5">
      {STAGES.map((stage) => {
        const isDelivered = stage === "Delivered";
        const canDropHere = canManage && (!isDelivered || dragTicket?.status === "Ready for pickup");
        const isOver = dragOverCol === stage;
        return (
          <div
            key={stage}
            onDragOver={(e) => { if (canDropHere) { e.preventDefault(); setDragOverCol(stage); } }}
            onDragLeave={() => setDragOverCol((c) => (c === stage ? null : c))}
            onDrop={(e) => { e.preventDefault(); if (canDropHere) handleDrop(stage); else setDragOverCol(null); }}
            className="min-h-[120px] p-2"
            style={{
              backgroundColor: isDelivered ? C.slip2 : "transparent",
              border: `1px dashed ${isOver && canDropHere ? C.orange : C.rule}`,
              opacity: dragTicket && !canDropHere ? 0.5 : 1,
            }}
          >
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.06em", color: isDelivered ? C.inkSoft : C.ink }}>{stage}</span>
              <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{byStage[stage].length}</span>
            </div>
            <div className="space-y-2">
              {byStage[stage].map((t) => (
                <div key={t.id} style={{ opacity: busyId === t.id ? 0.5 : 1 }}>
                  <KanbanCard
                    ticket={t}
                    draggable={mayMove(t)}
                    onDragStart={() => setDragTicket(t)}
                    onClick={() => onOpen(t.id)}
                  />
                </div>
              ))}
              {!byStage[stage].length && <p className="px-1 py-3 text-center text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Empty</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Repairs() {
  const { can, me } = useSession();
  const [mineOnly, setMineOnly] = useState(false);
  const [tickets, setTickets] = useState(null);
  const [parties, setParties] = useState([]);
  const [services, setServices] = useState([]);
  const [stockPoints, setStockPoints] = useState([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [view, setView] = useState("list");
  const [flash, setFlash] = useState("");
  const [created, setCreated] = useState(null);

  const load = useCallback((status) => api.getAll(`/tickets/${status !== "all" ? `?status=${encodeURIComponent(status)}` : ""}`).then(setTickets).catch((e) => setError(e.message)), []);

  useEffect(() => {
    api.getAll("/parties/").then(setParties);
    api.getAll("/services/").then(setServices);
    api.getAll("/stock-points/?active=1").then(setStockPoints);
  }, [load]);
  useEffect(() => { load(filter); }, [filter, load]);
  // a store was edited: tickets show its name, the new-ticket form lists it
  useEffect(() => onStoreChanged(() => {
    api.getAll("/stock-points/?active=1").then(setStockPoints).catch(() => {});
    load(filter);
  }), [filter, load]);

  if (!can("repairs.view")) return <div className="flex-1 px-8 py-10"><Locked label="Your role doesn't include repairs & service access." /></div>;
  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!tickets) return <Spinner label="Loading tickets…" />;

  const create = async (payload, isBulk = false) => {
    const result = await api.post(isBulk ? "/repair-orders/" : "/tickets/", payload);
    setTickets((current) => isBulk ? [...result.tickets, ...current] : [result, ...current]);
    setAdding(false);
    // estimate fixed by the Admin at booking: the client's approval link goes out now
    if (result.approval) setCreated({ code: isBulk ? result.code : result.code, approval: result.approval });
  };

  const onChanged = (t) => setTickets((l) => l.map((x) => (x.id === t.id ? t : x)));
  // "My jobs" is for the people who do the work; Super Admin / Admin oversee every ticket
  const showMine = !isAdminLevel(me);
  const shown = mineOnly && showMine ? tickets.filter((t) => t.assigned_to === me?.id) : tickets;

  const showError = (msg) => {
    setFlash(msg);
    setTimeout(() => setFlash(""), 6000);
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <PageHeader title="Repairs & service" subtitle="Ticket to bill, with parts availability checked against shared stock" />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <TabBar
          tabs={[{ id: "list", label: "List", icon: List }, { id: "board", label: "Board", icon: LayoutGrid }, ...(can("repairs.assign") ? [{ id: "staff", label: "Staff performance", icon: BarChart3 }] : [])]}
          value={view}
          onChange={setView}
        />
        {showMine && (
          <PillButton icon={UserCheck} primary={mineOnly} onClick={() => setMineOnly((v) => !v)}>My jobs ({tickets.filter((t) => t.assigned_to === me?.id).length})</PillButton>
        )}
        {can("repairs.book") && (
          <PillButton icon={Plus} primary onClick={() => setAdding(true)}>New ticket</PillButton>
        )}
      </div>

      {flash && (
        <div className="mt-3 flex items-center gap-2 px-3 py-2" style={{ backgroundColor: `${C.carbon}14`, border: `1px solid ${C.carbon}` }}>
          <X size={13} style={{ color: C.carbon }} />
          <span className="text-xs" style={{ fontFamily: F.body, color: C.ink }}>{flash}</span>
        </div>
      )}

      {created && (
        <div className="mt-3"><ApprovalLinkCard approval={created.approval} title={`${created.code} created · send the estimate for approval`} onClose={() => setCreated(null)} /></div>
      )}

      {view === "staff" && can("repairs.assign") ? <StaffPerformance /> : view === "list" ? (
        <>
          <div className="mt-5 overflow-x-auto">
            <TabBar
              tabs={["all", ...STAGES].map((s) => ({ id: s, label: s === "all" ? "All" : s }))}
              value={filter}
              onChange={setFilter}
            />
          </div>

          <div className="mt-3 space-y-2">
            {shown.map((t) => (
              <button key={t.id} onClick={() => setOpenId(t.id)} data-panel className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
                <div className="min-w-[160px] flex-1">
                  <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink }}>{t.code}{t.repair_type === "bulk" ? ` · ${t.order_code}` : ""}</span>
                  <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{t.party_name} · {t.brand} {t.model_name}</p>
                </div>
                <span className="flex items-center gap-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}><MapPinned size={12} />{t.stock_point_name}</span>
                <span className="flex items-center gap-1 text-xs" style={{ fontFamily: F.body, color: t.assigned_to ? C.stamp : C.inkSoft }}><UserCheck size={12} />{t.assigned_to ? t.assigned_to_name : "Unassigned"}</span>
                <span className="text-sm sm:min-w-20 sm:text-right" style={{ fontFamily: F.mono, fontWeight: 600, color: C.ink }}>{money(t.total)}</span>
                <Pill color={STAGE_COLOR[t.status]}>{t.status}</Pill>
              </button>
            ))}
            {!shown.length && <p className="px-2 py-10 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No tickets in this view.</p>}
          </div>
        </>
      ) : (
        <>
          {!can("repairs.manage") && (
            <p className="mt-4 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Your role can view the board but not drag tickets between stages.</p>
          )}
          <KanbanBoard tickets={shown} canManage={can("repairs.manage")} meId={me?.id} canAssign={can("repairs.assign")} onOpen={setOpenId} onMoved={onChanged} onError={showError} />
        </>
      )}

      {adding && <NewTicketModal parties={parties} services={services} stockPoints={stockPoints} onClose={() => setAdding(false)} onCreate={create} />}
      {openId && <TicketDetail ticketId={openId} onClose={() => setOpenId(null)} onChanged={onChanged} />}
    </div>
  );
}
