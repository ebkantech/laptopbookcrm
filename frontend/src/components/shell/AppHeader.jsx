import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, BadgeCheck, BarChart3, Briefcase, ChevronDown, ChevronRight, CornerDownLeft, Landmark,
  LayoutDashboard, LogOut, MapPin, Megaphone, Menu, Monitor, Moon, Package, Receipt, Repeat2, Search,
  Settings as SettingsIcon, Sun, User, Users, Wrench, X,
} from "lucide-react";

import { C, F, APP_NAME, APP_VERSION } from "../../lib/theme";
import { api } from "../../lib/api";
import { accessLabel } from "../../lib/accessLevel";
import { MODULES, canOpen, categoryOf, quickLinks, visibleCategories, visibleModules } from "../../lib/navConfig";
import { getThemeMode, onThemeChange, setThemeMode } from "../../lib/themeMode";
import NotificationBell from "../NotificationBell";
import StoreSwitcher from "../StoreSwitcher";
import BrandMark from "./BrandMark";

export const MODULE_ICONS = {
  home: LayoutDashboard, inventory: Package, storeLocator: MapPin, invoices: Receipt, parties: Users,
  rentals: Repeat2, leads: Briefcase, repairs: Wrench, warranty: BadgeCheck, accounting: Landmark,
  reports: BarChart3, broadcast: Megaphone, settings: SettingsIcon,
};

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "");
export const PALETTE_SHORTCUT = isMac ? "⌘K" : "Ctrl K";

function initials(me) {
  const a = (me?.first_name || "").trim()[0] || "";
  const b = (me?.last_name || "").trim()[0] || "";
  return (a + b).toUpperCase() || (me?.username || "?")[0].toUpperCase();
}
const fullName = (me) => `${me?.first_name || ""} ${me?.last_name || ""}`.trim() || me?.username || "";

function useThemeMode() {
  const [mode, setMode] = useState(getThemeMode);
  useEffect(() => onThemeChange((_, m) => setMode(m)), []);
  return [mode, (m) => { setThemeMode(m); setMode(m); }];
}

// Close a popover on outside click or Escape.
function useDismiss(open, close, refs) {
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (!refs.some((r) => r.current?.contains(e.target))) close();
    };
    const onKey = (e) => { if (e.key === "Escape") close(true); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
}

function Brand({ onHome }) {
  return (
    <button type="button" onClick={onHome} className="v2x-brand" aria-label={`${APP_NAME} — go to start`}>
      <BrandMark />
      <span className="min-w-0 text-left leading-none">
        <span className="block text-[17px]" style={{ fontFamily: F.editorial, fontWeight: 600, color: C.navInk, letterSpacing: "-0.01em" }}>
          Vantage<span style={{ color: C.cta }}>2x</span>
        </span>
        <span className="v2x-brand-sub mt-1 block whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.22em]" style={{ color: C.navInkSoft }}>{APP_VERSION}</span>
      </span>
    </button>
  );
}

/* One mega-menu: the category's modules as cards (icon, name, what it's
   for, its quick links), with the category blurb in a side column. */
function MegaMenu({ cat, me, view, onGo, onClose, menuRef }) {
  return (
    <div ref={menuRef} className="v2x-mega" role="menu" aria-label={cat.label}>
      <div className="v2x-mega-inner">
        <div className="v2x-mega-intro">
          <p className="text-[10px] font-bold uppercase tracking-[0.22em]" style={{ color: C.cta }}>{cat.label}</p>
          <p className="mt-2 text-[22px] leading-tight" style={{ fontFamily: F.editorial, color: C.navInk }}>{cat.blurb}</p>
          <p className="mt-3 text-[11px]" style={{ color: C.navInkSoft }}>
            Press <kbd className="v2x-kbd">{PALETTE_SHORTCUT}</kbd> to jump anywhere.
          </p>
        </div>
        <div className="v2x-mega-grid">
          {cat.modules.map((id) => {
            const Icon = MODULE_ICONS[id];
            const quick = quickLinks(me, id);
            const active = view === id;
            return (
              <div key={id} className="v2x-mega-card" data-active={active ? "" : undefined}>
                <button type="button" role="menuitem" className="v2x-mega-main" onClick={() => { onGo(id); onClose(); }}>
                  <span className="v2x-mega-icon"><Icon size={18} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 text-[14px] font-bold" style={{ color: C.navInk }}>
                      {MODULES[id].label}
                      <ArrowRight size={13} className="v2x-mega-arrow" />
                    </span>
                    <span className="mt-1 block text-[12px] leading-snug" style={{ color: C.navInkSoft }}>{MODULES[id].description}</span>
                  </span>
                </button>
                {quick.length > 0 && (
                  <div className="v2x-mega-quick">
                    {quick.map((q) => (
                      <button key={q.label} type="button" role="menuitem" onClick={() => { onGo(id, q.search); onClose(); }}>
                        <ChevronRight size={11} /> {q.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function UserMenu({ me, onLogout, onGo }) {
  const [open, setOpen] = useState(false);
  const btn = useRef(null);
  const box = useRef(null);
  const [mode, setMode] = useThemeMode();
  useDismiss(open, (esc) => { setOpen(false); if (esc) btn.current?.focus(); }, [btn, box]);
  const role = me.role_label || accessLabel(me);
  const themes = [{ id: "light", label: "Light", icon: Sun }, { id: "dark", label: "Dark", icon: Moon }, { id: "system", label: "Auto", icon: Monitor }];
  return (
    <div className="relative">
      <button ref={btn} type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu"
        aria-label={`Account: ${fullName(me)}`} className="v2x-avatar-btn">
        <span className="v2x-avatar">{initials(me)}</span>
        <span className="v2x-avatar-meta v2x-wide min-w-0 text-left">
          <span className="block max-w-[9rem] truncate text-[12px] font-bold" style={{ color: C.navInk }}>{fullName(me)}</span>
          {role && <span className="block max-w-[9rem] truncate text-[10px]" style={{ color: C.navInkSoft }}>{role}</span>}
        </span>
        <ChevronDown size={13} className="v2x-wide" style={{ color: C.navInkSoft }} />
      </button>
      {open && (
        <div ref={box} role="menu" className="v2x-pop absolute right-0 top-12 z-50 w-64 overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-3.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
            <span className="v2x-avatar" style={{ width: 38, height: 38 }}>{initials(me)}</span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-bold" style={{ color: C.ink }}>{fullName(me)}</span>
              <span className="block truncate text-xs" style={{ color: C.inkSoft }}>{role || me.username}</span>
            </span>
          </div>
          <div className="py-1.5">
            <button type="button" role="menuitem" className="v2x-menuitem" onClick={() => { setOpen(false); onGo("settings", "?tab=profile"); }}><User size={15} /> My profile</button>
            <button type="button" role="menuitem" className="v2x-menuitem" onClick={() => { setOpen(false); onGo("settings"); }}><SettingsIcon size={15} /> Settings</button>
          </div>
          <div className="px-4 pb-3 pt-1" style={{ borderTop: `1px solid ${C.rule}` }}>
            <p className="mb-2 mt-2.5 text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C.inkSoft }}>Appearance</p>
            <div className="v2x-seg" role="radiogroup" aria-label="Theme">
              {themes.map((t) => (
                <button key={t.id} type="button" role="radio" aria-checked={mode === t.id} onClick={() => setMode(t.id)}>
                  <t.icon size={13} /> {t.label}
                </button>
              ))}
            </div>
          </div>
          <button type="button" role="menuitem" className="v2x-menuitem" style={{ borderTop: `1px solid ${C.rule}`, color: C.red }} onClick={onLogout}>
            <LogOut size={15} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function ThemeToggle({ className = "v2x-navicon" }) {
  const [mode, setMode] = useThemeMode();
  const dark = document.documentElement.dataset.theme === "dark";
  return (
    <button type="button" className={className} onClick={() => setMode(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={`Theme: ${mode}`}>
      {dark ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}

export function AppHeader({ me, view, onGo, onLogout, onOpenPalette, onOpenDrawer, drawerOpen, toggleRef }) {
  const cats = visibleCategories(me);
  const [openCat, setOpenCat] = useState(null);
  const menuRef = useRef(null);
  const navRef = useRef(null);
  const hoverTimer = useRef(null);
  useDismiss(!!openCat, () => setOpenCat(null), [menuRef, navRef]);
  useEffect(() => () => clearTimeout(hoverTimer.current), []);
  const activeCat = categoryOf(view)?.id;
  const cat = cats.find((c) => c.id === openCat);

  const hoverOpen = (id) => {
    clearTimeout(hoverTimer.current);
    if (openCat) setOpenCat(id);   // already browsing: follow the pointer at once
    else hoverTimer.current = setTimeout(() => setOpenCat(id), 160);
  };
  const hoverLeave = () => { clearTimeout(hoverTimer.current); };

  return (
    <header className="v2x-header" onMouseLeave={() => { clearTimeout(hoverTimer.current); }}>
      <div className="v2x-header-row">
        <button ref={toggleRef} type="button" data-nav-toggle onClick={onOpenDrawer} aria-label="Open navigation menu"
          aria-expanded={drawerOpen} aria-controls="cb-nav-drawer" className="v2x-navicon lg:!hidden">
          <Menu size={20} />
        </button>
        <Brand onHome={() => onGo(visibleModules(me)[0] || "settings")} />
        <div className="hidden md:block"><span className="v2x-divider" /></div>
        <div className="hidden min-w-0 md:block"><StoreSwitcher /></div>

        <nav ref={navRef} aria-label="Main navigation" className="v2x-nav hidden lg:flex">
          {cats.map((c) => {
            const single = c.modules.length === 1;
            const Icon = single ? MODULE_ICONS[c.modules[0]] : null;
            const active = activeCat === c.id;
            const label = single ? MODULES[c.modules[0]].label : c.label;
            return (
              <button key={c.id} type="button" className="v2x-navcat" data-active={active ? "" : undefined}
                data-open={openCat === c.id ? "" : undefined}
                aria-current={active && single ? "page" : undefined}
                aria-expanded={single ? undefined : openCat === c.id}
                aria-haspopup={single ? undefined : "menu"}
                onMouseEnter={() => (single ? hoverLeave() : hoverOpen(c.id))}
                onMouseLeave={hoverLeave}
                onClick={() => {
                  if (single) { setOpenCat(null); onGo(c.modules[0]); } else setOpenCat((cur) => (cur === c.id ? null : c.id));
                }}>
                {Icon && <Icon size={15} />}
                <span>{label}</span>
                {!single && <ChevronDown size={13} className="v2x-caret" />}
              </button>
            );
          })}
        </nav>

        <div className="v2x-right">
          <button type="button" onClick={onOpenPalette} className="v2x-search" aria-label={`Search and jump (${PALETTE_SHORTCUT})`}>
            <Search size={15} />
            <span className="v2x-search-text">Search or jump to…</span>
            <kbd className="v2x-kbd v2x-search-kbd">{PALETTE_SHORTCUT}</kbd>
          </button>
          <NotificationBell />
          <span className="hidden xl:inline-flex"><ThemeToggle /></span>
          <button type="button" className="v2x-navicon hidden sm:inline-flex" data-active={view === "settings" ? "" : undefined}
            onClick={() => onGo("settings")} aria-label="Settings" title="Settings">
            <SettingsIcon size={17} />
          </button>
          <UserMenu me={me} onLogout={onLogout} onGo={onGo} />
        </div>
      </div>
      {cat && cat.modules.length > 1 && (
        <MegaMenu cat={cat} me={me} view={view} onGo={onGo} onClose={() => setOpenCat(null)} menuRef={menuRef} />
      )}
    </header>
  );
}

/* Below the header: where you are, and the other modules in the same
   category one click away. */
export function ContextBar({ me, view, onGo }) {
  const cat = categoryOf(view);
  const siblings = cat ? cat.modules.filter((id) => canOpen(me, id)) : [];
  const here = MODULES[view];
  if (!here) return null;
  return (
    <div className="v2x-context">
      <div className="v2x-context-row">
        <p className="v2x-crumbs">
          <span>{cat ? cat.crumb || cat.label : "Account"}</span>
          <ChevronRight size={12} />
          <strong>{here.label}</strong>
        </p>
        {siblings.length > 1 && <span className="v2x-context-sep" aria-hidden />}
        {siblings.length > 1 && (
          <nav aria-label={`${cat.label} modules`} className="v2x-ctx-tabs">
            {siblings.map((id) => {
              const Icon = MODULE_ICONS[id];
              return (
                <button key={id} type="button" className="v2x-ctx-tab" aria-current={view === id ? "page" : undefined} onClick={() => onGo(id)}>
                  <Icon size={14} /> {MODULES[id].label}
                </button>
              );
            })}
          </nav>
        )}
      </div>
    </div>
  );
}

export function MobileDrawer({ me, view, open, onClose, onGo, onLogout, closeRef }) {
  const cats = visibleCategories(me);
  const go = (id, search) => { onGo(id, search); onClose(false); };
  return (
    <div className={`fixed inset-0 z-50 lg:hidden ${open ? "" : "pointer-events-none"}`}>
      <div aria-hidden="true" className={`v2x-scrim ${open ? "opacity-100" : "opacity-0"}`} onClick={() => onClose(true)} />
      <aside id="cb-nav-drawer" role="dialog" aria-modal="true" aria-label="Navigation" aria-hidden={!open} inert={!open}
        className={`v2x-drawer ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex items-center justify-between gap-2 px-4 pt-4">
          <Brand onHome={() => go(visibleModules(me)[0] || "settings")} />
          <button ref={closeRef} type="button" onClick={() => onClose(true)} aria-label="Close navigation menu" className="v2x-navicon">
            <X size={18} />
          </button>
        </div>
        <div className="px-4"><StoreSwitcher variant="drawer" /></div>
        <nav aria-label="Main navigation" className="mt-4 min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {[...cats, { id: "account", label: accessLabel(me) || "Account", modules: ["settings"] }].map((c) => (
            <div key={c.id} className="mb-4">
              <p className="mb-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.2em]" style={{ color: C.navInkSoft }}>{c.label}</p>
              {c.modules.map((id) => {
                const Icon = MODULE_ICONS[id];
                const active = view === id;
                return (
                  <button key={id} type="button" onClick={() => go(id)} aria-current={active ? "page" : undefined} className="v2x-drawer-item">
                    <span className="v2x-mega-icon" style={{ width: 32, height: 32 }}><Icon size={16} /></span>
                    <span className="min-w-0 flex-1 text-left">
                      <span className="block text-[14px] font-semibold">{MODULES[id].label}</span>
                      <span className="block truncate text-[11px]" style={{ color: C.navInkSoft }}>{MODULES[id].description}</span>
                    </span>
                    {active && <span className="h-1.5 w-1.5 rounded-full" style={{ background: C.cta }} />}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="flex items-center gap-2.5 px-4 py-3" style={{ borderTop: `1px solid ${C.navLine}` }}>
          <span className="v2x-avatar">{initials(me)}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-bold" style={{ color: C.navInk }}>{fullName(me)}</span>
            <span className="block truncate text-[10px]" style={{ color: C.navInkSoft }}>{me.role_label || accessLabel(me)}</span>
          </span>
          <ThemeToggle />
          <button type="button" onClick={onLogout} aria-label="Sign out" title="Sign out" className="v2x-navicon"><LogOut size={16} /></button>
        </div>
      </aside>
    </div>
  );
}

/* Ctrl/Cmd+K: jump to any module or section, find a customer or supplier
   by name, or switch the theme. Only lists what this account can open. */
export function CommandPalette({ me, open, onClose, onGo }) {
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const [people, setPeople] = useState([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const canParties = canOpen(me, "parties");

  useEffect(() => {
    if (!open) return;
    setQ(""); setCursor(0); setPeople([]);
  }, [open]);

  const needle = q.trim().toLowerCase();
  useEffect(() => {
    if (!open || !canParties || needle.length < 2) { setPeople([]); setSearching(false); return undefined; }
    let alive = true;
    setSearching(true);
    const t = setTimeout(() => {
      api.get(`/parties/?q=${encodeURIComponent(needle)}`)
        .then((d) => { if (alive) setPeople((d.results ?? d).slice(0, 6)); })
        .catch(() => { if (alive) setPeople([]); })
        .finally(() => { if (alive) setSearching(false); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [needle, open, canParties]);

  const items = useMemo(() => {
    const out = [];
    const match = (text) => !needle || text.toLowerCase().includes(needle);
    // best first: a name that starts with what was typed, then one that
    // contains it, then a match only in the description
    const score = (label) => {
      const l = label.toLowerCase();
      return l.startsWith(needle) ? 0 : l.includes(needle) ? 1 : 2;
    };
    const nav = [];
    for (const id of visibleModules(me)) {
      const m = MODULES[id];
      if (match(`${m.label} ${m.description}`)) nav.push({ key: id, group: "Go to", label: m.label, hint: m.description, icon: MODULE_ICONS[id], run: () => onGo(id), rank: needle ? score(m.label) : 0 });
      for (const ql of quickLinks(me, id)) {
        if (needle && match(`${m.label} ${ql.label}`)) nav.push({ key: `${id}${ql.search}`, group: "Sections", label: ql.label, hint: m.label, icon: MODULE_ICONS[id], run: () => onGo(id, ql.search), rank: score(ql.label) });
      }
    }
    if (needle) {
      // keep each group together, ordered by its best match
      const best = {};
      for (const it of nav) best[it.group] = Math.min(best[it.group] ?? 9, it.rank);
      nav.sort((x, y) => (best[x.group] - best[y.group]) || (x.group === y.group ? x.rank - y.rank : x.group.localeCompare(y.group)));
    }
    out.push(...nav);
    for (const p of people) {
      out.push({ key: `party-${p.id}`, group: "Customers & suppliers", label: p.name, hint: [p.type, p.phone, p.city].filter(Boolean).join(" · "), icon: Users, run: () => onGo("parties", "", `/parties/${p.id}`) });
    }
    const themes = [["light", "Light theme", Sun], ["dark", "Dark theme", Moon], ["system", "Match my device", Monitor]];
    for (const [mode, label, icon] of themes) {
      if (needle && match(`${label} theme appearance`)) out.push({ key: `theme-${mode}`, group: "Appearance", label, icon, run: () => setThemeMode(mode) });
    }
    return out;
  }, [needle, people, me]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setCursor(0); }, [needle, people.length]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;
  const choose = (item) => { onClose(); item.run(); };
  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(items.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter" && items[cursor]) { e.preventDefault(); choose(items[cursor]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  let lastGroup = "";
  return (
    <div className="v2x-palette-wrap" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="v2x-palette" role="dialog" aria-modal="true" aria-label="Search and jump">
        <label className="v2x-palette-input">
          <Search size={17} style={{ color: C.inkSoft }} />
          <input ref={inputRef} autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder={canParties ? "Jump to a module, or find a customer by name…" : "Jump to a module or section…"}
            aria-label="Search" role="combobox" aria-expanded="true" aria-controls="v2x-palette-list"
            aria-activedescendant={items[cursor] ? `v2x-opt-${cursor}` : undefined} />
          <kbd className="v2x-kbd">Esc</kbd>
        </label>
        <ul id="v2x-palette-list" ref={listRef} role="listbox" className="v2x-palette-list">
          {items.map((item, i) => {
            const head = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            const Icon = item.icon;
            return (
              <li key={item.key} role="none">
                {head && <p className="v2x-palette-group">{head}</p>}
                <button type="button" role="option" id={`v2x-opt-${i}`} data-idx={i} aria-selected={i === cursor}
                  className="v2x-palette-item" onMouseMove={() => setCursor(i)} onClick={() => choose(item)}>
                  <span className="v2x-palette-icon"><Icon size={15} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-semibold">{item.label}</span>
                    {item.hint && <span className="block truncate text-[11.5px]" style={{ color: C.inkSoft }}>{item.hint}</span>}
                  </span>
                  {i === cursor && <CornerDownLeft size={14} style={{ color: C.inkSoft }} />}
                </button>
              </li>
            );
          })}
          {!items.length && !searching && <li className="px-4 py-8 text-center text-sm" style={{ color: C.inkSoft }}>Nothing matches “{q}”.</li>}
          {searching && <li className="px-4 py-2 text-xs" style={{ color: C.inkSoft }}>Searching customers…</li>}
        </ul>
        <div className="v2x-palette-foot">
          <span><kbd className="v2x-kbd">↑</kbd><kbd className="v2x-kbd">↓</kbd> move</span>
          <span><kbd className="v2x-kbd">↵</kbd> open</span>
          <span className="ml-auto" style={{ fontFamily: F.editorial }}>{APP_NAME}</span>
        </div>
      </div>
    </div>
  );
}
