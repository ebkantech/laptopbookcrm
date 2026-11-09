import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

import { TOAST_EVENT } from "../lib/toast";
import { C, F } from "../lib/theme";

const LIFETIME = 5000;
const STYLE = {
  success: { icon: CheckCircle2, color: C.green },
  info: { icon: Info, color: C.stamp },
  error: { icon: AlertCircle, color: C.carbon },
};

/* Shows toast.success / info / error messages in the bottom-right corner (top on phones). */
export default function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const timers = new Set();
    const add = (event) => {
      const item = event.detail;
      setItems((list) => [...list.slice(-3), item]);
      const timer = setTimeout(() => { setItems((list) => list.filter((x) => x.id !== item.id)); timers.delete(timer); }, LIFETIME);
      timers.add(timer);
    };
    window.addEventListener(TOAST_EVENT, add);
    return () => { window.removeEventListener(TOAST_EVENT, add); timers.forEach(clearTimeout); };
  }, []);
  if (!items.length) return null;
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-3 top-3 z-[2000] flex flex-col items-end gap-2 sm:inset-x-auto sm:bottom-24 sm:right-6 sm:top-auto">
      {items.map((t) => {
        const s = STYLE[t.kind] || STYLE.info;
        return (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"} data-toast={t.kind}
            className="crm-toast pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-xl px-3.5 py-3"
            style={{ backgroundColor: C.slip, border: `1px solid ${s.color}55`, borderLeft: `4px solid ${s.color}`, boxShadow: "0 10px 30px rgba(23,32,51,0.16)" }}>
            <s.icon size={18} className="mt-0.5 shrink-0" style={{ color: s.color }} />
            <div className="min-w-0 flex-1">
              <p className="text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>{t.text}</p>
              {t.detail && <p className="mt-0.5 text-xs" style={{ fontFamily: F.body, color: C.inkSoft }}>{t.detail}</p>}
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => setItems((list) => list.filter((x) => x.id !== t.id))}><X size={14} style={{ color: C.inkSoft }} /></button>
          </div>
        );
      })}
    </div>
  );
}
