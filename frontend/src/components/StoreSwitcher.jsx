import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Building2, Check, ChevronDown, Globe, Search, Store } from "lucide-react";
import { C, F } from "../lib/theme";
import { useSession } from "../context/SessionContext";
import { ALL_STORES, activeStoreValue, storeLabel } from "../lib/workContext";

const SEARCH_FROM = 7; // stores listed before a search box is worth showing

/*
 * The sidebar's store switcher: the store every page works in. Lists only
 * what GET /users/me/ says this account may reach (the server re-checks every
 * request); "All Stores" only for the Owner / Super Admin. The list opens in
 * a fixed-position panel so the sidebar's own scrolling can't clip it.
 */
export default function StoreSwitcher({ collapsed = false }) {
  const { me, switchStore, switching } = useSession();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [place, setPlace] = useState(null);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);

  const stores = me?.accessible_stores || [];
  const current = activeStoreValue(me);
  const label = storeLabel(me);
  const options = [
    ...(me?.can_select_all_stores ? [{ id: ALL_STORES, name: "All Stores", kind: "all" }] : []),
    ...stores,
  ];
  const canSwitch = options.length > 1;
  const needle = query.trim().toLowerCase();
  const shown = needle ? options.filter((o) => o.name.toLowerCase().includes(needle)) : options;

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const r = buttonRef.current.getBoundingClientRect();
    const width = Math.max(r.width, 240);
    setPlace({ top: r.bottom + 6, left: Math.min(r.left, window.innerWidth - width - 8), width });
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    const onDown = (e) => {
      if (!panelRef.current?.contains(e.target) && !buttonRef.current?.contains(e.target)) close();
    };
    const onKey = (e) => {
      if (e.key === "Escape") { close(); buttonRef.current?.focus(); }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  if (!me) return null;

  const choose = async (id) => {
    setOpen(false);
    setQuery("");
    if (id === current) return;
    setError("");
    try {
      await switchStore(id);
    } catch (e) {
      setError(e.message || "Couldn't switch store.");
    }
  };

  const iconFor = (o) => (o.kind === "all" ? Building2 : o.kind === "online" ? Globe : Store);
  const CurrentIcon = current === ALL_STORES ? Building2 : Store;

  return (
    <div className={collapsed ? "mt-5 flex justify-center" : "mt-5"}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => canSwitch && setOpen((v) => !v)}
        disabled={switching}
        aria-haspopup={canSwitch ? "listbox" : undefined}
        aria-expanded={canSwitch ? open : undefined}
        aria-label={`Store: ${label}${canSwitch ? ". Change store" : ""}`}
        title={collapsed ? `Store: ${label}` : undefined}
        className={`flex items-center gap-2.5 rounded-xl text-left transition-colors ${canSwitch ? "hover:bg-white/[0.07]" : "cursor-default"} ${collapsed ? "h-10 w-10 justify-center" : "w-full px-3 py-2"}`}
        style={{ backgroundColor: "rgba(255,255,255,0.045)", border: "1px solid rgba(255,255,255,0.08)", opacity: switching ? 0.7 : 1 }}
      >
        <CurrentIcon size={15} style={{ color: C.orange, flexShrink: 0 }} />
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block text-[9px] font-bold uppercase tracking-[0.18em]" style={{ color: "#858D9B" }}>Store</span>
              <span className="block truncate text-[13px] font-semibold text-white" style={{ fontFamily: F.body }}>
                {switching ? "Switching…" : label}
              </span>
            </span>
            {canSwitch && <ChevronDown size={14} className="shrink-0 transition-transform" style={{ color: "#A5ACB9", transform: open ? "rotate(180deg)" : "none" }} />}
          </>
        )}
      </button>
      {error && !collapsed && <p role="alert" className="mt-1.5 px-1 text-[11px]" style={{ color: "#FB8A8A" }}>{error}</p>}

      {open && place && (
        <div
          ref={panelRef}
          className="fixed z-50 overflow-hidden rounded-xl"
          style={{ top: place.top, left: place.left, width: place.width, background: "#FFFFFF", color: "#000000", colorScheme: "light", border: "1px solid #E5E7EB", boxShadow: "0 12px 32px rgba(15,23,42,0.18), 0 2px 6px rgba(15,23,42,0.08)", fontFamily: F.body }}
        >
          {options.length >= SEARCH_FROM && (
            <label className="flex items-center gap-2 px-3 py-2" style={{ borderBottom: "1px solid #E5E7EB" }}>
              <Search size={13} style={{ color: "#6B7280" }} />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search stores"
                aria-label="Search stores"
                className="w-full bg-transparent text-xs text-black outline-none placeholder:text-[#6B7280]"
              />
            </label>
          )}
          <ul role="listbox" aria-label="Stores" className="max-h-72 overflow-y-auto py-1">
            {shown.map((o) => {
              const Icon = iconFor(o);
              const selected = o.id === current;
              return (
                <li key={o.id} role="option" aria-selected={selected}>
                  <button
                    type="button"
                    onClick={() => choose(o.id)}
                    autoFocus={selected && options.length < SEARCH_FROM}
                    className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors focus:outline-none ${selected ? "" : "hover:bg-[#F3F4F6] focus:bg-[#F3F4F6]"}`}
                    style={{ color: "#000000", fontWeight: selected ? 700 : 500, ...(selected && { backgroundColor: `${C.orange}14`, boxShadow: `inset 3px 0 0 ${C.orange}` }) }}
                  >
                    <Icon size={14} style={{ color: selected ? C.orange : "#6B7280", flexShrink: 0 }} />
                    <span className="min-w-0 flex-1 truncate">{o.name}</span>
                    {o.kind === "online" && <span className="text-[10px]" style={{ color: "#6B7280" }}>Online</span>}
                    {o.is_active === false && <span className="text-[10px]" style={{ color: "#6B7280" }}>Inactive</span>}
                    {selected && <Check size={13} style={{ color: C.orange, flexShrink: 0 }} />}
                  </button>
                </li>
              );
            })}
            {!shown.length && <li className="px-3 py-3 text-xs" style={{ color: "#6B7280" }}>No store matches “{query}”.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
