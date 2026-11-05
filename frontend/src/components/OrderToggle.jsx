import { ArrowDownNarrowWide, ArrowUpNarrowWide } from "lucide-react";
import { C, F } from "../lib/theme";

/* "Oldest first" / "Newest first" switch for a ledger: a soft track with the
 * chosen option raised as a white pill. */
export default function OrderToggle({ value, onChange, label = "Order" }) {
  const opt = (dir, Icon, text) => {
    const active = value === dir;
    return (
      <button type="button" role="radio" aria-checked={active} onClick={() => onChange(dir)}
        className="flex min-h-[30px] items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-xs transition-colors duration-150"
        style={{
          fontFamily: F.body, fontWeight: active ? 700 : 500,
          color: active ? C.stamp : C.inkSoft,
          backgroundColor: active ? C.slip : "transparent",
          boxShadow: active ? "0 1px 3px rgba(23, 32, 51, 0.14)" : "none",
        }}>
        <Icon size={13} strokeWidth={active ? 2.4 : 2} aria-hidden="true" />{text}
      </button>
    );
  };
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex items-center gap-0.5 rounded-full p-1"
      style={{ backgroundColor: C.paper, border: `1px solid ${C.rule}` }}>
      {opt("asc", ArrowDownNarrowWide, "Oldest first")}
      {opt("desc", ArrowUpNarrowWide, "Newest first")}
    </div>
  );
}
