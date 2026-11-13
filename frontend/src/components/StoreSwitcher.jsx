import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Building2, Check, ChevronDown, Globe, Search, Store } from "lucide-react";
import { C, F } from "../lib/theme";
import { useSession } from "../context/SessionContext";
import { ALL_STORES, activeStoreValue, storeLabel } from "../lib/workContext";

const SEARCH_FROM = 7; // stores listed before a search box is worth showing

/*
 * The workspace selector: the store every page works in. Lists only what
 * GET /users/me/ says this account may reach (the server re-checks every
 * request); "All Stores" only for the Owner / Super Admin. The list opens in
 * a fixed-position panel so the header / drawer can't clip it.
 * `variant="drawer"` is the full-width version for the mobile drawer.
 */
export default function StoreSwitcher({ variant = "header" }) {
  const drawer = variant === "drawer";
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
    <div className={drawer ? "mt-4" : "min-w-0"}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => canSwitch && setOpen((v) => !v)}
        disabled={switching}
        aria-haspopup={canSwitch ? "listbox" : undefined}
        aria-expanded={canSwitch ? open : undefined}
        aria-label={`Store: ${label}${canSwitch ? ". Change store" : ""}`}
        title={`Workspace: ${label}`}
        className={`v2x-workspace ${canSwitch ? "" : "cursor-default"} ${drawer ? "w-full" : ""}`}
        data-static={canSwitch ? undefined : ""}
        style={{ opacity: switching ? 0.7 : 1 }}
      >
        <CurrentIcon size={14} style={{ color: C.cta, flexShrink: 0 }} />
        <span className="min-w-0 flex-1">
          <span className="v2x-ws-label block text-[9px] font-bold uppercase tracking-[0.18em]" style={{ color: C.navInkSoft }}>Workspace</span>
          <span className="block truncate text-[12.5px] font-semibold" style={{ fontFamily: F.body, color: C.navInk }}>
            {switching ? "Switching…" : label}
          </span>
        </span>
        {canSwitch && <ChevronDown size={14} className="shrink-0 transition-transform" style={{ color: C.navInkSoft, transform: open ? "rotate(180deg)" : "none" }} />}
      </button>
      {error && <p role="alert" className={drawer ? "mt-1.5 px-1 text-[11px]" : "v2x-pop fixed right-4 top-16 z-50 px-3 py-2 text-[11px]"} style={{ color: drawer ? "#F7A398" : C.red }}>{error}</p>}

      {open && place && (
        <div
          ref={panelRef}
          className="v2x-pop fixed z-[60] overflow-hidden"
          style={{ top: place.top, left: place.left, width: place.width, fontFamily: F.body }}
        >
          {options.length >= SEARCH_FROM && (
            <label className="flex items-center gap-2 px-3 py-2" style={{ borderBottom: `1px solid ${C.rule}` }}>
              <Search size={13} style={{ color: C.inkSoft }} />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search stores"
                aria-label="Search stores"
                className="w-full bg-transparent text-xs outline-none"
                style={{ color: C.ink, border: 0, boxShadow: "none", padding: 0, minHeight: 0 }}
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
                    className="v2x-menuitem flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px]"
                    style={{ color: C.ink, fontWeight: selected ? 700 : 500, ...(selected && { backgroundColor: `color-mix(in srgb, ${C.cta} 14%, transparent)`, boxShadow: `inset 3px 0 0 ${C.cta}` }) }}
                  >
                    <Icon size={14} style={{ color: selected ? C.ink : C.inkSoft, flexShrink: 0 }} />
                    <span className="min-w-0 flex-1 truncate">{o.name}</span>
                    {o.kind === "online" && <span className="text-[10px]" style={{ color: C.inkSoft }}>Online</span>}
                    {o.is_active === false && <span className="text-[10px]" style={{ color: C.inkSoft }}>Inactive</span>}
                    {selected && <Check size={13} style={{ color: C.green, flexShrink: 0 }} />}
                  </button>
                </li>
              );
            })}
            {!shown.length && <li className="px-3 py-3 text-xs" style={{ color: C.inkSoft }}>No store matches “{query}”.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
