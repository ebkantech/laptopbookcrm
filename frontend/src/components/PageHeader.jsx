import { useEffect, useRef, useState } from "react";
import { Bell, HelpCircle } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";

function timeAgo(iso) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// The header bell -- polls its own unread count every 30s while
// mounted (the page header remounts on navigation, so this is a
// fresh poll per page rather than one long-lived global timer) and
// loads the full list lazily, the first time the dropdown opens.
function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState("");
  const boxRef = useRef(null);

  const loadCount = () => api.get("/my-notifications/unread_count/").then((d) => setUnread(d.count)).catch(() => {});
  const loadList = () => api.get("/my-notifications/").then(setItems).catch((e) => setError(e.message || "Couldn't load notifications."));

  useEffect(() => {
    loadCount();
    const t = setInterval(loadCount, 30000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (open && !items) loadList();
  }, [open]);

  useEffect(() => {
    const onClickAway = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  const markRead = async (id) => {
    setItems((cur) => cur.map((n) => (n.id === id ? { ...n, read_at: n.read_at || new Date().toISOString() } : n)));
    setUnread((c) => Math.max(0, c - 1));
    try {
      await api.post(`/my-notifications/${id}/mark_read/`);
    } catch {
      // best-effort -- the optimistic update above already reflects
      // the intent; a failed mark-read just means it may still show
      // as unread on the next poll, not worth surfacing an error for
    }
  };

  const markAllRead = async () => {
    setItems((cur) => cur?.map((n) => ({ ...n, read_at: n.read_at || new Date().toISOString() })) ?? cur);
    setUnread(0);
    try {
      await api.post("/my-notifications/mark_all_read/");
    } catch {
      // best-effort, see markRead
    }
  };

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-full"
        style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}
      >
        <Bell size={15} style={{ color: C.inkSoft }} />
        {unread > 0 && (
          <span
            className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px]"
            style={{ backgroundColor: C.carbon, color: "#FFFFFF", fontFamily: F.mono, fontWeight: 700 }}
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          className="absolute right-0 top-11 z-30 max-h-96 w-80 overflow-y-auto"
          data-panel
          style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}
        >
          <div className="flex items-center justify-between px-3 py-2.5" style={{ borderBottom: `1px solid ${C.rule}` }}>
            <span className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 700, letterSpacing: "0.08em", color: C.inkSoft }}>Notifications</span>
            {unread > 0 && (
              <button onClick={markAllRead} className="text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: C.stamp }}>Mark all read</button>
            )}
          </div>
          {error ? (
            <p className="px-3 py-6 text-center text-xs" style={{ fontFamily: F.body, color: C.carbon }}>{error}</p>
          ) : !items ? (
            <p className="px-3 py-6 text-center text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Loading…</p>
          ) : items.length ? (
            items.map((n) => (
              <button
                key={n.id}
                onClick={() => !n.read_at && markRead(n.id)}
                className="block w-full px-3 py-2.5 text-left"
                style={{ borderBottom: `1px solid ${C.rule}`, backgroundColor: n.read_at ? "transparent" : `${C.stamp}0D` }}
              >
                <p className="text-xs" style={{ fontFamily: F.body, fontWeight: n.read_at ? 500 : 700, color: C.ink }}>{n.subject}</p>
                {n.body && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{n.body}</p>}
                <p className="mt-1 text-[10px]" style={{ fontFamily: F.mono, color: C.inkSoft }}>{timeAgo(n.created_at)}</p>
              </button>
            ))
          ) : (
            <p className="px-3 py-6 text-center text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>Nothing yet.</p>
          )}
        </div>
      )}
    </div>
  );
}

// A small, deterministic set of avatar background colors -- picked by a
// hash of the user's id/name so the same person always gets the same
// color, and different people on the same team don't all look identical.
const AVATAR_COLORS = [C.stamp, C.green, C.blue, C.carbon, C.amber];
function avatarColor(seed) {
  let hash = 0;
  for (const ch of String(seed)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}
function initials(me) {
  const a = (me.first_name || "").trim()[0] || "";
  const b = (me.last_name || "").trim()[0] || "";
  return (a + b).toUpperCase() || (me.username || "?")[0].toUpperCase();
}

/**
 * Shared page header -- title + subtitle on the left, notification bell,
 * help icon, and the signed-in user's avatar on the right, with an
 * optional `actions` slot for a page's own buttons (e.g. "New rental
 * agreement", "Export Excel") rendered just before those icons. One
 * component so every page's header reads as the same system rather than
 * each page hand-rolling its own title row.
 */
export default function PageHeader({ title, subtitle, actions }) {
  const { me } = useSession();

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p style={{ fontFamily: F.display, fontWeight: 700, fontSize: 24, color: C.ink }}>{title}</p>
        {subtitle && <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <NotificationBell />
        <button className="flex h-9 w-9 items-center justify-center rounded-full" style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }}>
          <HelpCircle size={15} style={{ color: C.inkSoft }} />
        </button>
        {me && (
          <span
            title={`${me.first_name} ${me.last_name} — ${me.role_label || (me.is_superuser ? "Superuser" : "")}`}
            className="flex h-9 w-9 items-center justify-center rounded-full"
            style={{ backgroundColor: avatarColor(me.id ?? me.username), color: C.onAccent, fontFamily: F.display, fontWeight: 700, fontSize: 13 }}
          >
            {initials(me)}
          </span>
        )}
      </div>
    </div>
  );
}
