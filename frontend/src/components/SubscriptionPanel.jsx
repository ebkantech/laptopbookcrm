import { useEffect, useState } from "react";

import { ErrorNote, Spinner } from "./Atoms";
import { api } from "../lib/api";
import { C, F, fmt, money } from "../lib/theme";

const STATE_LABEL = { none: "No plan set", active: "Active", grace: "Grace period", read_only: "Read-only" };
const DURATIONS = [1, 3, 6, 12];

export default function SubscriptionPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get("/subscription/").then(setData).catch((e) => setError(e.message)); }, []);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner label="Loading subscription…" />;
  const priceFor = (plan, months) => plan.prices.find((price) => price.months === months)?.amount;
  const heading = { fontFamily: F.display, fontWeight: 700, color: C.ink };
  return (
    <div className="max-w-3xl space-y-5">
      <section className="p-4" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <p className="m-0 text-sm" style={heading}>{data.package || "No plan set"}</p>
        <p className="m-0 mt-1 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>
          {STATE_LABEL[data.state]}{data.ends_on ? ` · ends ${fmt(data.ends_on)} · ${data.months} month${data.months === 1 ? "" : "s"}` : ""}
        </p>
        {data.modules.length > 0 && <p className="m-0 mt-3 text-xs" style={{ fontFamily: F.body, color: C.ink }}>Includes: {data.modules.join(", ")}</p>}
      </section>
      <section className="overflow-x-auto" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
        <table className="w-full min-w-[520px] text-xs" style={{ fontFamily: F.body, color: C.ink }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${C.rule}`, color: C.inkSoft }}>
              <th className="px-4 py-2 text-left font-semibold">Package</th>
              {DURATIONS.map((months) => <th key={months} className="px-3 py-2 text-right font-semibold">{months} month{months === 1 ? "" : "s"}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.plans.map((plan) => (
              <tr key={plan.key} style={{ borderBottom: `1px solid ${C.rule}` }}>
                <td className="px-4 py-3">
                  <span style={{ fontWeight: 600 }}>{plan.name}</span>
                  <span className="mt-1 block" style={{ color: C.inkSoft }}>{plan.modules.join(", ")}</span>
                </td>
                {DURATIONS.map((months) => {
                  const amount = priceFor(plan, months);
                  return <td key={months} className="px-3 py-3 text-right align-top" style={{ fontFamily: F.mono }}>{amount === 0 ? "Free" : amount == null ? "—" : money(amount)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <p className="m-0 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>To start or renew a plan, contact your provider.</p>
    </div>
  );
}
