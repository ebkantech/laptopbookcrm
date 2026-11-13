import { AlertTriangle } from "lucide-react";

import { useSession } from "../context/SessionContext";
import { C, F } from "../lib/theme";

const REMIND_FROM_DAYS = 7;

// Shown across the app when the plan is about to end, or already has.
export default function SubscriptionBanner() {
  const { me } = useSession();
  const plan = me?.subscription;
  if (!plan || plan.state === "none") return null;
  let text = "";
  if (plan.state === "read_only") text = "Your subscription has ended. The CRM is read-only until you renew.";
  else if (plan.state === "grace") text = "Your subscription has ended. Renew soon to avoid read-only mode.";
  else if (plan.days_left <= REMIND_FROM_DAYS) text = `Your subscription ends in ${plan.days_left} day${plan.days_left === 1 ? "" : "s"}.`;
  if (!text) return null;
  const color = plan.state === "active" ? C.amber : C.carbon;
  return (
    <p role="status" className="m-0 flex shrink-0 items-center gap-2 px-5 py-2 text-xs sm:px-8" style={{ fontFamily: F.body, color: C.ink, backgroundColor: `color-mix(in srgb, ${color} 8%, transparent)`, borderBottom: `1px solid color-mix(in srgb, ${color} 33%, transparent)` }}>
      <AlertTriangle size={13} style={{ color }} /> {text}
    </p>
  );
}
