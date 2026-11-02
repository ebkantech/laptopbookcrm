import { Fragment, useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { ErrorNote, Pill, Spinner, TabBar } from "../Atoms";
import { attentionOrder, delayLabel, formatHours, hasProblems, onTimeRate } from "./performanceModel";
import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

const PERIODS = [{ id: "today", label: "Today" }, { id: "month", label: "This month" }, { id: "year", label: "This year" }, { id: "custom", label: "Custom" }];
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

function JobTable({ jobs, open }) {
  if (!jobs.length) return <p className="py-2 text-xs" style={{ color: C.inkSoft }}>{open ? "No open jobs." : "No finished jobs in this period."}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs" style={{ fontFamily: F.body }}>
        <thead><tr style={{ color: C.inkSoft }}>
          <th className="py-1 pr-3">Job</th><th className="pr-3">Device</th><th className="pr-3">Store</th><th className="pr-3">Given</th>
          <th className="pr-3">Diagnosed</th><th className="pr-3">{open ? "Due" : "Finished"}</th><th className="pr-3">{open ? "Open for" : "Time taken"}</th><th>Status</th>
        </tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} style={{ borderTop: `1px solid ${C.rule}`, backgroundColor: j.delayed ? `${C.carbon}12` : "transparent" }}>
              <td className="py-1.5 pr-3" style={{ fontFamily: F.mono, fontWeight: 700 }}>{j.code}<div style={{ fontFamily: F.body, fontWeight: 400, color: C.inkSoft }}>{j.party}</div></td>
              <td className="pr-3">{j.device}</td><td className="pr-3">{j.store}</td><td className="pr-3">{fmt(j.assigned_at)}</td>
              <td className="pr-3">{j.diagnosed_at ? <span title={j.diagnosis_note}>{fmt(j.diagnosed_at)}{j.hours_to_diagnose != null ? ` · ${formatHours(j.hours_to_diagnose)}` : ""}</span> : "—"}</td>
              <td className="pr-3">{open ? fmt(j.due_at) : fmt(j.ready_at)}</td>
              <td className="pr-3" style={{ fontFamily: F.mono }}>{formatHours(open ? j.hours_open : j.hours_taken)}</td>
              <td><span style={{ color: j.delayed ? C.carbon : C.green, fontWeight: 600 }}>{delayLabel(j)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Admin / Super Admin only: what each repair staff member finished, how long it took, and what ran late.
export default function StaffPerformance() {
  const [period, setPeriod] = useState("month");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [data, setData] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (period === "custom" && !(from && to)) return;
    const q = period === "custom" ? `?period=custom&date_from=${from}&date_to=${to}` : `?period=${period}`;
    setError("");
    api.get(`/repair-staff-report/${q}`).then(setData).catch((e) => setError(e.body?.detail || e.message));
  }, [period, from, to]);
  useEffect(() => { load(); }, [load]);

  const rows = data ? attentionOrder(data.staff) : [];
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-center gap-2">
        <TabBar tabs={PERIODS} value={period} onChange={setPeriod} />
        {period === "custom" && <>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}` }} aria-label="From" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}` }} aria-label="To" />
        </>}
      </div>
      <ErrorNote message={error} />
      {!data && !error && <Spinner label="Loading staff report…" />}
      {data && <>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          {[["Finished", data.totals.done, C.ink], ["Finished late", data.totals.delayed, data.totals.delayed ? C.carbon : C.ink], ["Open & overdue", data.totals.overdue_open, data.totals.overdue_open ? C.carbon : C.ink]].map(([l, v, c]) => (
            <div key={l} className="px-2 py-2" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
              <p className="text-lg" style={{ fontFamily: F.mono, fontWeight: 700, color: c }}>{v}</p><p className="text-xs" style={{ color: C.inkSoft }}>{l}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          <table className="w-full text-left text-xs" style={{ fontFamily: F.body }}>
            <thead><tr style={{ color: C.inkSoft }}>
              <th className="p-2">Staff</th><th>Today</th><th>Month</th><th>Year</th><th>In period</th><th>On time</th><th>Avg time</th><th>Open</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => {
                const rate = onTimeRate(r.period);
                const expanded = openId === r.id;
                return (
                  <Fragment key={r.id}>
                    <tr onClick={() => setOpenId(expanded ? null : r.id)} className="cursor-pointer" style={{ borderTop: `1px solid ${C.rule}`, backgroundColor: hasProblems(r) ? `${C.carbon}0F` : "transparent" }}>
                      <td className="p-2" style={{ fontWeight: 600 }}>{expanded ? <ChevronDown size={12} className="mr-1 inline" /> : <ChevronRight size={12} className="mr-1 inline" />}{r.name}<div style={{ fontWeight: 400, color: C.inkSoft }}>{r.store || "No store"}</div></td>
                      <td style={{ fontFamily: F.mono }}>{r.counts.today}</td><td style={{ fontFamily: F.mono }}>{r.counts.month}</td><td style={{ fontFamily: F.mono }}>{r.counts.year}</td>
                      <td style={{ fontFamily: F.mono }}>{r.period.done}</td>
                      <td>{rate === null ? "—" : <span style={{ color: rate < 70 ? C.carbon : C.green, fontWeight: 600 }}>{rate}%</span>}{r.period.delayed > 0 && <Pill color={C.carbon}>{r.period.delayed} late</Pill>}</td>
                      <td style={{ fontFamily: F.mono }}>{formatHours(r.period.avg_hours)}</td>
                      <td style={{ fontFamily: F.mono }}>{r.open}{r.overdue > 0 && <Pill color={C.carbon}>{r.overdue} overdue</Pill>}</td>
                    </tr>
                    {expanded && (
                      <tr><td colSpan={8} className="p-3" style={{ backgroundColor: C.slip2 }}>
                        <p className="mb-1 text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 600 }}>Open jobs</p>
                        <JobTable jobs={r.open_jobs} open />
                        <p className="mb-1 mt-3 text-xs uppercase" style={{ color: C.inkSoft, fontWeight: 600 }}>Finished {data.date_from === data.date_to ? data.date_from : `${data.date_from} to ${data.date_to}`}</p>
                        <JobTable jobs={r.jobs} />
                      </td></tr>
                    )}
                  </Fragment>
                );
              })}
              {!rows.length && <tr><td colSpan={8} className="p-4" style={{ color: C.inkSoft }}>No repair staff found.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs" style={{ color: C.inkSoft }}>A job counts as late when it was finished (or is still open) after its promised date — or {" "}3 days after it was received if none was promised. Time taken runs from when the job was given to the staff member.</p>
      </>}
    </div>
  );
}
