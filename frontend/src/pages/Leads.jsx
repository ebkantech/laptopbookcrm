import { useCallback, useEffect, useMemo, useState } from "react";
import { Briefcase, MapPin, Plus } from "lucide-react";
import { C, F, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, ErrorNote, Pill, SearchInput, Spinner, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";
import LeadDetail from "../components/leads/LeadDetail";
import LeadFormModal from "../components/leads/LeadFormModal";
import { PRIORITY, TABS, inTab, statusOf } from "../components/leads/leadModel";

const when = (v) => (v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

export default function Leads() {
  const { can, me } = useSession();
  const [leads, setLeads] = useState(null);
  const [stockPoints, setStockPoints] = useState([]);
  const [tab, setTab] = useState("active");
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => api.getAll("/leads/").then(setLeads).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); api.getAll("/stock-points/?active=1").then((all) => setStockPoints(all)).catch(() => {}); }, [load]);

  const openLead = async (id) => {
    try { setOpen(await api.get(`/leads/${id}/`)); } catch (e) { setError(e.message); }
  };
  const changed = (lead) => { setOpen(lead); load(); };

  const counts = useMemo(() => Object.fromEntries(TABS.map((t) => [t.id, (leads || []).filter((l) => inTab(l, t.id)).length])), [leads]);
  const shown = useMemo(() => {
    const q = term.trim().toLowerCase();
    return (leads || []).filter((l) => inTab(l, tab) && (!q || [l.code, l.party_name, l.site_address, l.device, l.contact_phone].some((x) => (x || "").toLowerCase().includes(q))));
  }, [leads, tab, term]);

  if (error && !leads) return <div className="flex-1 px-8 py-10"><ErrorNote message={error} /></div>;
  if (!leads) return <Spinner label="Loading on-site jobs…" />;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <PageHeader
        title="On-site service"
        subtitle={can("leads.assign") || can("leads.manage") ? "Laptop repairs at the client's site — visit, diagnose, approve, repair, collect" : "Your assigned on-site jobs"}
        actions={can("leads.create") && <button type="button" onClick={() => setCreating(true)} className="flex min-h-9 items-center gap-1.5 rounded-full px-4 py-2 text-xs" style={{ backgroundColor: C.orange, color: C.onAccent, fontFamily: F.body, fontWeight: 700 }}><Plus size={13} /> New job</button>}
      />
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <TabBar value={tab} onChange={setTab} tabs={TABS.map((t) => ({ id: t.id, label: `${t.label} (${counts[t.id]})` }))} />
        <SearchInput value={term} onChange={setTerm} placeholder="Search job, client, address…" className="min-w-[200px] flex-1" ariaLabel="Search jobs" />
      </div>
      <ErrorNote message={error} />
      {shown.length === 0 ? (
        <div data-panel className="mt-6 p-10 text-center text-sm" style={{ color: C.inkSoft }}><Briefcase className="mx-auto mb-2" size={22} />{term ? "No job matches your search." : "No jobs here."}</div>
      ) : (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((l) => {
            const st = statusOf(l.status);
            return (
              <button key={l.id} type="button" onClick={() => openLead(l.id)} data-panel className="p-4 text-left" aria-label={`Open job ${l.code}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0"><p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{l.code}</p><p className="truncate text-base" style={{ fontFamily: F.display, fontWeight: 700 }}>{l.party_name}</p></div>
                  <Pill color={C[st.tone] || C.inkSoft}>{st.label}</Pill>
                </div>
                <p className="mt-2 flex items-start gap-1.5 text-xs" style={{ color: C.inkSoft }}><MapPin size={12} className="mt-0.5 shrink-0" /><span className="line-clamp-2 break-words">{l.site_address}</span></p>
                <p className="mt-2 line-clamp-2 break-words text-sm">{l.issue}</p>
                <div className="mt-3 flex items-center justify-between gap-2 text-xs" style={{ color: C.inkSoft }}>
                  <span className="truncate">{l.assigned_to_name || "Unassigned"}{l.preferred_at && ` · ${when(l.preferred_at)}`}</span>
                  <span className="flex shrink-0 items-center gap-2">{l.priority === "urgent" && <Pill color={C.carbon}>{PRIORITY.urgent}</Pill>}{l.quote_total != null && <strong style={{ fontFamily: F.mono, color: C.ink }}>{money(l.quote_total)}</strong>}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
      {open && <LeadDetail lead={open} stockPoints={stockPoints} onChange={changed} onClose={() => { setOpen(null); load(); }} />}
      {creating && <LeadFormModal stockPoints={stockPoints} defaultStore={me?.stock_point} onClose={() => setCreating(false)} onSaved={(l) => { setCreating(false); load(); setOpen(l); }} />}
    </div>
  );
}
