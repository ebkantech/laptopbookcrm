import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";

function timeAgo(iso) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// The header bell -- polls its own unread count every 30s while mounted
// (it lives in the app header, so one poll for the whole session) and
// loads the full list lazily, the first time the panel opens.
export default function NotificationBell() {
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
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className="v2x-navicon relative"
      >
        <Bell size={17} />
        {unread > 0 && (
          <span
            className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px]"
            style={{ backgroundColor: C.cta, color: C.onCta, fontFamily: F.mono, fontWeight: 800, boxShadow: `0 0 0 2px ${C.nav}` }}
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          className="v2x-pop absolute right-0 top-12 z-50 max-h-[26rem] w-[22rem] max-w-[calc(100vw-1.5rem)] overflow-y-auto"
          role="dialog"
          aria-label="Notifications"
        >
          <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: `1px solid ${C.rule}` }}>
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
                className="v2x-notif block w-full px-4 py-3 text-left"
                data-unread={n.read_at ? undefined : ""}
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

