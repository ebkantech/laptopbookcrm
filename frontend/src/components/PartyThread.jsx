import { useEffect, useState } from "react";
import { Mail, MessageCircle, Send, X } from "lucide-react";
import { C, F } from "../lib/theme";
import { api } from "../lib/api";
import { Spinner } from "./Atoms";

/** Bare thread -- needs the party's messages already loaded. */
export function PartyThread({ partyId, messages, onSent, defaultChannel = "whatsapp" }) {
  const [ch, setCh] = useState(defaultChannel);
  const [text, setText] = useState("");
  const meta = { whatsapp: { color: C.green, icon: MessageCircle }, email: { color: C.blue, icon: Mail } };
  const shown = messages.filter((m) => m.channel === ch);

  const send = async () => {
    if (!text.trim()) return;
    const msg = await api.post(`/parties/${partyId}/message/`, { channel: ch, body: text.trim() });
    onSent(msg);
    setText("");
  };

  return (
    <div data-panel style={{ border: `1px solid ${C.rule}`, backgroundColor: C.slip2 }}>
      <div className="flex" style={{ borderBottom: `1px solid ${C.rule}` }}>
        {["whatsapp", "email"].map((k) => {
          const m = meta[k];
          const on = ch === k;
          return (
            <button key={k} onClick={() => setCh(k)} className="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs" style={{ fontFamily: F.body, fontWeight: 600, color: on ? m.color : C.inkSoft, backgroundColor: on ? `${m.color}17` : "transparent", borderBottom: `2px solid ${on ? m.color : "transparent"}` }}>
              <m.icon size={13} /> {k === "whatsapp" ? "WhatsApp" : "Email"}
            </button>
          );
        })}
      </div>
      <div className="space-y-2 px-3 py-3" style={{ maxHeight: 190, overflowY: "auto" }}>
        {shown.map((m) => (
          <div key={m.id} className={m.direction === "in" ? "pr-10" : "pl-10 text-right"}>
            <p className="inline-block px-3 py-1.5 text-xs" style={{ fontFamily: F.body, color: m.direction === "out" ? C.onAccent : C.ink, backgroundColor: m.direction === "out" ? meta[ch].color : C.slip, textAlign: "left" }}>{m.body}</p>
            <p className="mt-0.5 text-xs" style={{ fontFamily: F.mono, color: C.inkSoft }}>{new Date(m.at).toLocaleString()}</p>
          </div>
        ))}
        {!shown.length && <p className="text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>No {ch === "whatsapp" ? "WhatsApp" : "email"} messages yet.</p>}
      </div>
      <div className="flex items-center gap-2 px-3 pb-3">
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder={`Message over ${ch === "whatsapp" ? "WhatsApp" : "email"}`}
          className="flex-1 bg-transparent px-2.5 py-1.5 text-xs outline-none" style={{ fontFamily: F.body, color: C.ink, border: `1px solid ${C.rule}`, backgroundColor: C.slip }} />
        <button onClick={send} style={{ color: meta[ch].color }}><Send size={15} /></button>
      </div>
    </div>
  );
}

/** Self-contained modal -- fetches the party's own messages, so callers
 * only need a partyId (used from Rentals to chat about a raised issue,
 * without needing the full Parties list loaded). */
export function PartyChatModal({ partyId, partyName, onClose }) {
  const [messages, setMessages] = useState(null);

  useEffect(() => {
    api.get(`/parties/${partyId}/`).then((p) => setMessages(p.messages));
  }, [partyId]);

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(4,9,18,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-sm p-5" data-panel style={{ backgroundColor: C.slip, border: `1px solid ${C.rule}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase" style={{ fontFamily: F.body, fontWeight: 600, letterSpacing: "0.1em", color: C.inkSoft }}>Chat with</p>
            <p className="text-sm" style={{ fontFamily: F.display, fontWeight: 600, color: C.ink }}>{partyName}</p>
          </div>
          <button onClick={onClose}><X size={16} style={{ color: C.inkSoft }} /></button>
        </div>
        <div className="mt-3">
          {messages === null ? <Spinner /> : (
            <PartyThread partyId={partyId} messages={messages} onSent={(m) => setMessages((list) => [...list, m])} />
          )}
        </div>
      </div>
    </div>
  );
}
