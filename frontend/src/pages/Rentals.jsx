import { useEffect, useState } from "react";
import {
  AlertOctagon, Check, Clock3, MessageCircle, MessageSquarePlus, Phone,
  ShieldAlert, UserPlus, X,
} from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Pill, Spinner, ErrorNote } from "../components/Atoms";
import { PartyChatModal } from "../components/PartyThread";

const BAND_COLOR = { "High risk": C.carbon, Watch: C.amber, Healthy: C.green };
const ISSUE_STATUS_COLOR = { Open: C.carbon, "In progress": C.amber, Resolved: C.green };

function RaiseIssueModal({ rentalId, onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const issue = await api.post("/rental-issues/", { rental: rentalId, title: title.trim(), description: description.trim() });
      onCreated(issue);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between"><Eyebrow>Raise an issue</Eyebrow><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Log what the client is reporting about their rented equipment.</p>
        <div className="mt-4 space-y-3">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Screen flickering" className="w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="Details the client gave you" className="w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
        </div>
        <ErrorNote message={error} />
        <button onClick={submit} disabled={busy} className="mt-4 flex w-full items-center justify-center gap-1.5 py-2.5 text-xs uppercase" style={{ backgroundColor: C.carbon, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", opacity: busy ? 0.7 : 1 }}>
          <AlertOctagon size={13} /> {busy ? "Raising…" : "Raise issue"}
        </button>
      </div>
    </div>
  );
}

function IssueRow({ issue, staff, onAssigned, onResolved }) {
  const { can } = useSession();
  const [assigning, setAssigning] = useState(false);

  const assign = async (userId) => {
    const updated = await api.post(`/rental-issues/${issue.id}/assign/`, { assigned_to: userId });
    onAssigned(updated);
    setAssigning(false);
  };
  const resolve = async () => {
    const updated = await api.post(`/rental-issues/${issue.id}/resolve/`);
    onResolved(updated);
  };

  return (
    <div className="px-3 py-2.5" style={{ backgroundColor: C.slip2 }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{issue.title}</p>
          {issue.description && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{issue.description}</p>}
          <p className="mt-1 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>
            Raised {new Date(issue.raised_at).toLocaleDateString("en-IN")}
            {issue.assigned_to_name && ` · assigned to ${issue.assigned_to_name}`}
          </p>
        </div>
        <Pill color={ISSUE_STATUS_COLOR[issue.status]}>{issue.status}</Pill>
      </div>

      {can("rentals.manage") && issue.status !== "Resolved" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {assigning ? (
            <select autoFocus onBlur={() => setAssigning(false)} onChange={(e) => e.target.value && assign(+e.target.value)}
              className="bg-transparent px-2 py-1 text-xs outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              <option value="">Assign to…</option>
              {staff.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>)}
            </select>
          ) : (
            <button onClick={() => setAssigning(true)} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
              <UserPlus size={11} /> {issue.assigned_to_name ? "Reassign" : "Assign"}
            </button>
          )}
          <button onClick={resolve} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.green}`, color: C.green, fontFamily: F.body, fontWeight: 600 }}>
            <Check size={11} /> Mark resolved
          </button>
        </div>
      )}
    </div>
  );
}

export default function Rentals() {
  const { can } = useSession();
  const [rentals, setRentals] = useState(null);
  const [staff, setStaff] = useState([]);
  const [error, setError] = useState("");
  const [raisingFor, setRaisingFor] = useState(null);
  const [chatWith, setChatWith] = useState(null);

  useEffect(() => {
    api.get("/rentals/").then((d) => setRentals(d.results ?? d)).catch((e) => setError(e.message));
    api.get("/users/").then((d) => setStaff(d.results ?? d));
  }, []);

  const patchRental = (rentalId, issue) => {
    setRentals((list) => list.map((r) => {
      if (r.id !== rentalId) return r;
      const exists = r.issues.some((i) => i.id === issue.id);
      const issues = exists ? r.issues.map((i) => (i.id === issue.id ? issue : i)) : [issue, ...r.issues];
      const open_issue_count = issues.filter((i) => i.status !== "Resolved").length;
      return { ...r, issues, open_issue_count };
    }));
  };

  if (error) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!rentals) return <Spinner label="Loading rentals…" />;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 20, color: C.ink }}>Rental accounts</p>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Churn risk, next payment due, and client-raised issues — highest risk first</p>

      <div className="mt-6 space-y-3">
        {rentals.map((r) => {
          const left = r.tenure_months - r.months_paid;
          return (
            <div key={r.id} data-panel className="p-4" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{r.party_name}</p>
                  <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{r.product_label} · {money(r.monthly_fee)}/mo</p>
                </div>
                <div className="flex items-center gap-2">
                  {r.open_issue_count > 0 && <Pill color={C.carbon}><ShieldAlert size={11} />{r.open_issue_count} open issue{r.open_issue_count !== 1 ? "s" : ""}</Pill>}
                  <Pill color={BAND_COLOR[r.churn_band]}>{r.churn_band} — {r.churn_score}/100</Pill>
                </div>
              </div>

              {/* next payment -- called out on its own row so it can't be missed */}
              <div className="mt-3 flex items-center gap-2 px-3 py-2" style={{ backgroundColor: r.next_payment_overdue ? `${C.carbon}14` : C.slip2, border: `1px solid ${r.next_payment_overdue ? C.carbon : C.rule}` }}>
                <Clock3 size={13} style={{ color: r.next_payment_overdue ? C.carbon : C.inkSoft }} />
                <span className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Next recurring payment due</span>
                <span className="text-sm" style={{ fontFamily: F.mono, fontWeight: 700, color: r.next_payment_overdue ? C.carbon : C.ink }}>{fmt(r.next_payment_date)}</span>
                {r.next_payment_overdue && <Pill color={C.carbon}>Overdue</Pill>}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Tenure</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{r.months_paid}/{r.tenure_months} mo</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Months left</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{left}</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Late payments</p><p className="text-sm" style={{ fontFamily: F.mono, color: r.late_count ? C.carbon : C.ink }}>{r.late_count}</p></div>
                <div><p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Last payment</p><p className="text-sm" style={{ fontFamily: F.mono, color: C.ink }}>{fmt(r.last_payment)}</p></div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={() => setRaisingFor(r.id)} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}>
                  <MessageSquarePlus size={12} /> Raise issue
                </button>
                <button onClick={() => setChatWith({ id: r.party, name: r.party_name })} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ backgroundColor: C.green, color: C.onAccent, fontFamily: F.body, fontWeight: 600 }}>
                  <MessageCircle size={12} /> Chat on WhatsApp
                </button>
                {r.churn_score >= 60 && (
                  <button className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.inkSoft }}><Phone size={12} />Call customer</button>
                )}
              </div>

              {r.issues.length > 0 && (
                <div className="mt-3 space-y-2">
                  <Eyebrow>Issues raised</Eyebrow>
                  {r.issues.map((issue) => (
                    <IssueRow key={issue.id} issue={issue} staff={staff}
                      onAssigned={(updated) => patchRental(r.id, updated)}
                      onResolved={(updated) => patchRental(r.id, updated)} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {!rentals.length && <p className="text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>No rental accounts yet.</p>}
      </div>

      {raisingFor && (
        <RaiseIssueModal rentalId={raisingFor} onClose={() => setRaisingFor(null)}
          onCreated={(issue) => { patchRental(raisingFor, issue); setRaisingFor(null); }} />
      )}
      {chatWith && <PartyChatModal partyId={chatWith.id} partyName={chatWith.name} onClose={() => setChatWith(null)} />}
    </div>
  );
}
