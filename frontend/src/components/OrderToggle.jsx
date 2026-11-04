import { ArrowDown, ArrowUp } from "lucide-react";
import { C, F } from "../lib/theme";

/* "Oldest first" / "Newest first" switch for a ledger: arrow down = reads
 * from the oldest at the top down to the newest, arrow up = newest at the top. */
export default function OrderToggle({ value, onChange, label = "Order" }) {
  const opt = (dir, Icon, text) => (
    <button type="button" role="radio" aria-checked={value === dir} onClick={() => onChange(dir)}
      className="flex min-h-[32px] items-center gap-1 px-2.5 text-xs"
      style={{ fontFamily: F.body, fontWeight: 600, color: value === dir ? C.onAccent : C.inkSoft, backgroundColor: value === dir ? C.stamp : "transparent" }}>
      <Icon size={13} aria-hidden="true" />{text}
    </button>
  );
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex overflow-hidden" style={{ border: `1px solid ${C.rule}` }}>
      {opt("asc", ArrowDown, "Oldest first")}
      {opt("desc", ArrowUp, "Newest first")}
    </div>
  );
}
