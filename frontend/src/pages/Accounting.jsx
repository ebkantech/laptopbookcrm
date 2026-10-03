import { useEffect, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, FileText, Landmark, Plus, Settings2, Wallet, X } from "lucide-react";
import { C, F, fmt, money } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Locked, Pill, PillButton, Spinner, ErrorNote, StatCard, TabBar } from "../components/Atoms";
import PageHeader from "../components/PageHeader";

/* Entries posted automatically from an invoice payment carry its code. */
function InvoiceTag({ code }) {
  if (!code) return null;
  return <span className="ml-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px]" style={{ fontFamily: F.mono, fontWeight: 600, color: C.stamp, backgroundColor: `${C.stamp}14` }}><FileText size={9} />{code}</span>;
}

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

  useEffect(() => { api.getAll("/cash-entries/").then(setEntries); }, []);
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
        <div>
          <Eyebrow>Cash book entries</Eyebrow>
          <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Cash payments recorded on invoices appear here automatically.</p>
        </div>
        {can("cashbook.edit") && <PillButton icon={Plus} primary onClick={() => setAdding(true)}>Add entry</PillButton>}
      </div>
      <div className="mt-3 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>{["Date", "Particulars", "By", "In", "Out", "Balance"].map((h) => <th key={h} className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{fmt(e.date)}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{e.particulars}<InvoiceTag code={e.invoice_code} /></td>
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

const fieldStyle = { fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, background: C.slip };

function NewBankEntry({ account, onClose, onAdd }) {
  const [type, setType] = useState("out");
  const [particulars, setParticulars] = useState("");
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");
  const save = async () => {
    if (!particulars.trim() || !(+amount > 0)) return setError("Enter the particulars and an amount.");
    try {
      await onAdd({ account: account.id, type, particulars: particulars.trim(), amount: +amount, reference: reference.trim(), date });
    } catch (e) {
      setError(Object.values(e.body || {}).flat().join(" ") || e.message);
    }
  };
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between"><Eyebrow>New entry · {account.name}</Eyebrow><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>
        <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>For money that isn't an invoice payment — rent, salaries, supplier payments, bank charges. Invoice payments are posted automatically.</p>
        <div className="mt-4 space-y-3">
          <div className="flex" style={{ border: `1px solid ${C.rule}` }}>
            {[["in", "Credit (money in)"], ["out", "Debit (money out)"]].map(([t, label]) => (
              <button key={t} onClick={() => setType(t)} className="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: type === t ? (t === "in" ? C.green : C.carbon) : C.inkSoft, backgroundColor: type === t ? C.slip2 : "transparent" }}>
                {t === "in" ? <ArrowDownCircle size={13} /> : <ArrowUpCircle size={13} />} {label}
              </button>
            ))}
          </div>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full px-3 py-2 text-sm outline-none" style={{ ...fieldStyle, fontFamily: F.mono }} />
          <input value={particulars} onChange={(e) => setParticulars(e.target.value)} placeholder="Particulars, e.g. Shop rent — October" className="w-full px-3 py-2 text-sm outline-none" style={fieldStyle} />
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder="Amount (₹)" className="w-full px-3 py-2 text-sm outline-none" style={{ ...fieldStyle, fontFamily: F.mono }} />
          <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Reference (UTR / cheque no., optional)" className="w-full px-3 py-2 text-sm outline-none" style={{ ...fieldStyle, fontFamily: F.mono }} />
        </div>
        <ErrorNote message={error} />
        <button onClick={save} className="mt-4 w-full py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>Add entry</button>
      </div>
    </div>
  );
}

function AccountSettings({ account, onClose, onSaved }) {
  const [name, setName] = useState(account?.name || "");
  const [opening, setOpening] = useState(String(account?.opening ?? ""));
  const [isDefault, setIsDefault] = useState(account ? account.is_default : true);
  const [error, setError] = useState("");
  const save = async () => {
    if (!name.trim()) return setError("Give the account a name, e.g. HDFC Bank — Current A/c.");
    const body = { name: name.trim(), opening: +opening || 0, is_default: isDefault };
    try {
      onSaved(account ? await api.patch(`/bank-accounts/${account.id}/`, body) : await api.post("/bank-accounts/", body));
    } catch (e) {
      setError(Object.values(e.body || {}).flat().join(" ") || e.message);
    }
  };
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }}>
      <div className="w-full max-w-sm p-6" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
        <div className="flex items-center justify-between"><Eyebrow>{account ? "Bank account settings" : "Add bank account"}</Eyebrow><button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button></div>
        <div className="mt-4 space-y-3">
          <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Account name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="HDFC Bank — Current A/c ••4821" className="mt-1 w-full px-3 py-2 text-sm outline-none" style={fieldStyle} /></label>
          <label className="text-xs" style={{ display: "block", color: C.inkSoft }}>Opening balance (₹)<input value={opening} onChange={(e) => setOpening(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full px-3 py-2 text-sm outline-none" style={{ ...fieldStyle, fontFamily: F.mono }} /></label>
          <label className="flex items-center gap-2 text-sm" style={{ display: "flex", color: C.ink }}><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} /> UPI, card, bank transfer and cheque payments on invoices go into this account</label>
        </div>
        <ErrorNote message={error} />
        <button onClick={save} className="mt-4 w-full py-2.5 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>Save</button>
      </div>
    </div>
  );
}

function BankBook() {
  const { can } = useSession();
  const [accounts, setAccounts] = useState(null);
  const [accountId, setAccountId] = useState(null);
  const [adding, setAdding] = useState(false);
  const [settings, setSettings] = useState(null); // "new" | account

  const load = (selectId) => api.getAll("/bank-accounts/").then((list) => {
    setAccounts(list);
    setAccountId((cur) => selectId ?? cur ?? (list.find((a) => a.is_default) || list[0])?.id);
  });
  useEffect(() => { load(); }, []);
  if (!can("bankbook.view")) return <Locked label="Your role doesn't include bank book access." />;
  if (!accounts) return <Spinner />;
  if (!accounts.length) {
    return (
      <div className="p-6 text-sm" data-panel style={{ border: `1px dashed ${C.rule}`, color: C.inkSoft }}>
        No bank account yet. UPI, card, bank-transfer and cheque payments on invoices are posted to your business account.
        {can("bankbook.edit") && <div className="mt-3"><PillButton icon={Plus} primary onClick={() => setSettings("new")}>Add bank account</PillButton></div>}
        {settings && <AccountSettings account={null} onClose={() => setSettings(null)} onSaved={(a) => { setSettings(null); load(a.id); }} />}
      </div>
    );
  }

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
          <button key={a.id} onClick={() => setAccountId(a.id)} className="px-3 py-1.5 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: accountId === a.id ? C.onAccent : C.inkSoft, backgroundColor: accountId === a.id ? C.stamp : "transparent", border: `1px solid ${accountId === a.id ? C.stamp : C.rule}` }}>{a.name}{a.is_default ? " · invoice payments" : ""}</button>
        ))}
        {can("bankbook.edit") && acc && (
          <button onClick={() => setSettings(acc)} className="flex items-center gap-1 px-2 py-1.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft, border: `1px solid ${C.rule}` }}><Settings2 size={12} /> Name & opening balance</button>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <StatCard label="Bank balance" value={money(acc?.balance)} icon={Landmark} />
        <StatCard label="Unreconciled entries" value={unreconciled} trend={unreconciled ? "down" : undefined} />
      </div>
      <div className="mt-4 flex items-center justify-between">
        <div>
          <Eyebrow>Transactions</Eyebrow>
          {acc?.is_default && <p className="mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>UPI, card, bank-transfer and cheque payments on invoices are posted here automatically — tick them off against the bank statement.</p>}
        </div>
        {can("bankbook.edit") && acc && <PillButton icon={Plus} primary onClick={() => setAdding(true)}>Add entry</PillButton>}
      </div>
      <div className="mt-3 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}` }}>
        <table className="w-full table table-borderless table-sm mb-0" style={{ borderCollapse: "collapse" }}>
          <thead><tr>{["Date", "Particulars", "Reference", "In", "Out", "Balance", "Status"].map((h) => <th key={h} className="px-3 py-2 text-left text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{fmt(e.date)}</td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.body, color: C.ink, borderBottom: `1px solid ${C.rule}` }}>{e.particulars}<InvoiceTag code={e.invoice_code} /></td>
                <td className="px-3 py-2 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft, borderBottom: `1px solid ${C.rule}` }}>{e.reference || "—"}</td>
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
      {adding && acc && (
        <NewBankEntry account={acc} onClose={() => setAdding(false)} onAdd={async (body) => { await api.post("/bank-entries/", body); setAdding(false); await load(acc.id); }} />
      )}
      {settings && <AccountSettings account={settings === "new" ? null : settings} onClose={() => setSettings(null)} onSaved={(a) => { setSettings(null); load(a.id); }} />}
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
      <PageHeader title="Accounting" subtitle="Cash and bank books — invoice payments post here automatically" />
      <div className="mt-5">
        <TabBar tabs={tabs} value={tab} onChange={setTab} />
      </div>
      <div className="mt-5">
        {tab === "cash" && <CashBook />}
        {tab === "bank" && <BankBook />}
      </div>
    </div>
  );
}
