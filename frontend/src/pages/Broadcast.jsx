import { useEffect, useState } from "react";
import { Mail, MessageCircle, Send } from "lucide-react";
import { C, F, fmt } from "../lib/theme";
import { api } from "../lib/api";
import { useSession } from "../context/SessionContext";
import { Eyebrow, Locked, Pill, Spinner } from "../components/Atoms";

export default function Broadcast() {
  const { can } = useSession();
  const [campaigns, setCampaigns] = useState(null);
  const [orders, setOrders] = useState([]);
  const [title, setTitle] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [audience, setAudience] = useState("All retail customers");

  useEffect(() => {
    api.get("/campaigns/").then((d) => setCampaigns(d.results ?? d));
    api.get("/whatsapp-orders/").then((d) => setOrders(d.results ?? d));
  }, []);

  if (!campaigns) return <Spinner label="Loading broadcast…" />;

  const send = async () => {
    if (!title.trim() || !can("broadcast.send")) return;
    const c = await api.post("/campaigns/", { title: title.trim(), channel, audience });
    setCampaigns((l) => [c, ...l]);
    setTitle("");
  };

  const quote = async (id) => {
    const o = await api.post(`/whatsapp-orders/${id}/quote/`);
    setOrders((l) => l.map((x) => (x.id === id ? o : x)));
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8">
      <p style={{ fontFamily: F.display, fontWeight: 600, fontSize: 20, color: C.ink }}>Broadcast</p>
      <p className="mt-1 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>Send offers and new-arrival alerts over WhatsApp or email</p>

      {can("broadcast.send") ? (
        <div className="mt-6 p-4" data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
          <Eyebrow>New campaign</Eyebrow>
          <textarea value={title} onChange={(e) => setTitle(e.target.value)} rows={2} placeholder="e.g. New arrival: ThinkPad T14 refurbished stock, limited units"
            className="mt-2 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }} />
          <div className="mt-3 flex flex-wrap gap-3">
            <div className="flex" style={{ border: `1px solid ${C.rule}` }}>
              {["whatsapp", "email"].map((c) => (
                <button key={c} onClick={() => setChannel(c)} className="flex items-center gap-1.5 px-3 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: channel === c ? (c === "whatsapp" ? C.green : C.stamp) : C.inkSoft, backgroundColor: channel === c ? C.slip2 : "transparent" }}>
                  {c === "whatsapp" ? <MessageCircle size={13} /> : <Mail size={13} />} {c === "whatsapp" ? "WhatsApp" : "Email"}
                </button>
              ))}
            </div>
            <select value={audience} onChange={(e) => setAudience(e.target.value)} className="flex-1 min-w-[180px] bg-transparent px-3 py-2 text-sm outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}` }}>
              <option>All retail customers</option><option>Dealers</option><option>Rentals ending in 30 days</option><option>Wishlist — Apple</option><option>Cold — no purchase in 90 days</option>
            </select>
            <button onClick={send} className="flex items-center gap-1.5 px-4 py-2 text-xs uppercase" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em" }}>
              <Send size={13} /> Send
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-6"><Locked label="Your role doesn't include broadcast sending." /></div>
      )}

      <Eyebrow>Recent campaigns</Eyebrow>
      <div className="mt-3 space-y-2">
        {campaigns.map((b) => (
          <div key={b.id} data-panel className="flex flex-wrap items-center justify-between gap-3 px-4 py-3" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{b.title}</p>
              <p className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{b.audience} · {fmt(b.at)}</p>
            </div>
            <Pill color={b.channel === "whatsapp" ? C.green : C.stamp}>{b.channel}</Pill>
            <span className="text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{b.sent} sent · {b.opened} opened</span>
          </div>
        ))}
      </div>

      <p className="mt-8 text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.14em", color: C.inkSoft }}>Incoming WhatsApp orders</p>
      <div className="mt-3 space-y-2">
        {orders.map((w) => (
          <div key={w.id} data-panel className="flex flex-wrap items-start justify-between gap-3 px-4 py-3" style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip }}>
            <div className="min-w-0 flex-1">
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 600, color: C.ink }}>{w.party_name}</p>
              <p className="mt-0.5 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>{w.text}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Pill color={w.status === "Quoted" ? C.green : C.amber}>{w.status}</Pill>
              {w.status === "New" && <button onClick={() => quote(w.id)} className="px-2 py-1 text-xs" style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 600 }}>Quote it</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
