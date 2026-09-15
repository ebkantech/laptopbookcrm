import { useEffect, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, Landmark, Plus, Wallet, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Locked, Pill, Spinner, ErrorNote, StatCard } from "../components/Atoms";

function NewCashEntry({ onClose, onAdd }) {
  const [particulars, setParticulars] = useState("");
  const [type, setType] = useState("in");
  const [amount, setAmount] = useState("");

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between"><Eyebrow>New cash entry</Eyebrow><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>
        <div className="mt-4 space-y-3">
          <div className="flex" style={{ border: `1px solid ${C.rule}` }}>
            {["in", "out"].map((t) => (
              <button key={t} onClick={() => setType(t)} className="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, color: type === t ? (t === "in" ? C.green : C.carbon) : C.inkSoft, backgroundColor: type === t ? C.slip2 : "transparent" }}>
                {t === "in" ? <ArrowDownCircle size={13} /> : <ArrowUpCircle size={13} />} Cash {t}
              </button>
            ))}
          </div>
          <input value={particulars} onChange={(e) => setParticulars(e.target.value)} placeholder="Particulars" className="w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder="Amount (₹)" className="w-full bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.mono, color: C.ink, border: `1px solid ${C.rule}` }} />
        </div>
        <button onClick={() => { if (particulars.trim() && +amount > 0) onAdd({ particulars: particulars.trim(), type, amount: +amount, date: new Date().toISOString().slice(0, 10) }); }}
          className="mt-4 w-full py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
          Add entry
        </button>
      </div>
    </div>
  );
}

function CashBook() {
  const { can } = useSession();
  const [entries, setEntries] = useState(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => { api.get("/cash-entries/").then((d) => setEntries(d.results ?? d)); }, []);
  if (!can("cashbook.view")) return <Locked label="Your role doesn't include cash book access." />;
  if (!entries) return <Spinner />;

  let running = 0;
  const rows = entries.map((e) => { running += e.type === "in" ? e.amount : -e.amount; return { ...e, balance: running }; });
  const balance = running;
  const totalIn = entries.filter((e) => e.type === "in").reduce((s, e) => s + e.amount, 0);
  const totalOut = entries.filter((e) => e.type === "out").reduce((s, e) => s + e.amount, 0);

  const add = async (payload) => {
    const e = await api.post("/cash-entries/", payload);
    setEntries((l) => [...l, e]);
    setAdding(false);
  };

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Cash balance" value={money(balance)} icon={Wallet} />
        <StatCard label="Total received" value={money(totalIn)} trend="up" icon={ArrowDownCircle} />
        <StatCard label="Total paid out" value={money(totalOut)} trend="down" icon={ArrowUpCircle} />
      </div>
      <div className="mt-4 flex items-center justify-between">
        <Eyebrow>Cash book entries</Eyebrow>
        {can("cashbook.edit") && <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em" }}><Plus size={13} /> Add entry</button>}
      </div>
      <div className="mt-3 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>{["Date", "Particulars", "By", "In", "Out", "Balance"].map((h) => <th key={h} className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{fmt(e.date)}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{e.particulars}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{e.by_name || "—"}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.green, borderBottom: `1px solid ${C.rule}` }}>{e.type === "in" ? money(e.amount) : ""}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.carbon, borderBottom: `1px solid ${C.rule}` }}>{e.type === "out" ? money(e.amount) : ""}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{money(e.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <NewCashEntry onClose={() => setAdding(false)} onAdd={add} />}
    </div>
  );
}

function BankBook() {
  const { can } = useSession();
  const [accounts, setAccounts] = useState(null);
  const [accountId, setAccountId] = useState(null);

  useEffect(() => { api.get("/bank-accounts/").then((d) => { const list = d.results ?? d; setAccounts(list); setAccountId(list[0]?.id); }); }, []);
  if (!can("bankbook.view")) return <Locked label="Your role doesn't include bank book access." />;
  if (!accounts) return <Spinner />;

  const acc = accounts.find((a) => a.id === accountId);
  const unreconciled = acc?.entries.filter((e) => !e.reconciled).length || 0;

  let running = acc?.opening || 0;
  const rows = (acc?.entries || []).filter((e) => e.particulars !== "Opening balance").map((e) => { running += e.type === "in" ? e.amount : -e.amount; return { ...e, balance: running }; });

  const toggle = async (entryId) => {
    const updated = await api.post(`/bank-entries/${entryId}/toggle-reconciled/`);
    setAccounts((list) => list.map((a) => (a.id !== accountId ? a : { ...a, entries: a.entries.map((e) => (e.id === entryId ? updated : e)) })));
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {accounts.map((a) => (
          <button key={a.id} onClick={() => setAccountId(a.id)} className="px-3 py-1.5 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: accountId === a.id ? C.onAccent : C.inkSoft, backgroundColor: accountId === a.id ? C.stamp : "transparent", border: `1px solid ${accountId === a.id ? C.stamp : C.rule}` }}>{a.name}</button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <StatCard label="Bank balance" value={money(acc?.balance)} icon={Landmark} />
        <StatCard label="Unreconciled entries" value={unreconciled} trend={unreconciled ? "down" : undefined} />
      </div>
      <Eyebrow>Transactions</Eyebrow>
      <div className="mt-3 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>{["Date", "Particulars", "In", "Out", "Balance", "Status"].map((h) => <th key={h} className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{fmt(e.date)}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{e.particulars}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.green, borderBottom: `1px solid ${C.rule}` }}>{e.type === "in" ? money(e.amount) : ""}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.carbon, borderBottom: `1px solid ${C.rule}` }}>{e.type === "out" ? money(e.amount) : ""}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, fontWeight: 700, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{money(e.balance)}</td>
                <td className="px-3 py-2 text-xs" style={{ borderBottom: `1px solid ${C.rule}` }}>
                  {can("bankbook.reconcile") ? <button onClick={() => toggle(e.id)}><Pill color={e.reconciled ? C.green : C.amber}>{e.reconciled ? "Reconciled" : "Pending"}</Pill></button> : <Pill color={e.reconciled ? C.green : C.amber}>{e.reconciled ? "Reconciled" : "Pending"}</Pill>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Accounting() {
  const [tab, setTab] = useState("cash");
  const tabs = [
    { id: "cash", label: "Cash book", icon: Wallet },
    { id: "bank", label: "Bank book", icon: Landmark },
  ];
  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 20, color: C.ink }}>Accounting</p>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Cash and bank working flow, gated by role</p>
      <div className="mt-5 flex gap-4" style={{ borderBottom: `1px solid ${C.rule}` }}>
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className="flex items-center gap-1.5 pb-2 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.08em", color: tab === t.id ? C.ink : C.inkSoft, borderBottom: `2px solid ${tab === t.id ? C.orange : "transparent"}` }}>
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>
      <div className="mt-5">
        {tab === "cash" && <CashBook />}
        {tab === "bank" && <BankBook />}
      </div>
    </div>
  );
}
