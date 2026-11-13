import { useState } from "react";
import { ExternalLink, LayoutDashboard } from "lucide-react";

import { api } from "../../lib/api";
import { C, F } from "../../lib/theme";

/*
 * "Open my portal" at the foot of the rental / repair approval pages. The
 * approval link gets the customer their portal link; signing in still takes
 * the one-time code we email them, so the button says where it went.
 */
export default function OpenPortal({ endpoint, decided }) {
  const [state, setState] = useState({ busy: false, error: "", email: "" });
  const open = async () => {
    setState({ busy: true, error: "", email: "" });
    try {
      const result = await api.publicPost(`${endpoint}portal/`, {});
      setState({ busy: false, error: "", email: result.email });
      window.location.assign(result.url);
    } catch (requestError) {
      setState({ busy: false, error: requestError.body?.detail || requestError.message, email: "" });
    }
  };
  return (
    <section className="mt-6 p-4 rounded-xl" style={{ border: `1px solid color-mix(in srgb, ${C.stamp} 27%, transparent)`, backgroundColor: `color-mix(in srgb, ${C.stamp} 4%, transparent)` }}>
      <p className="flex items-center gap-2 text-sm" style={{ fontFamily: F.body, fontWeight: 700, color: C.ink }}>
        <LayoutDashboard size={16} style={{ color: C.stamp }} /> Your customer portal
      </p>
      <p className="mt-1 text-xs leading-5" style={{ fontFamily: F.body, color: C.inkSoft }}>
        {decided
          ? "Follow your job, see invoices and pay, download documents and message us — all in one place."
          : "You can also see everything with us in your portal — jobs, invoices, documents and messages."}
        {" "}We'll email you a one-time code to sign in.
      </p>
      <button type="button" onClick={open} disabled={state.busy}
        className="mt-3 flex min-h-[44px] w-full items-center justify-center gap-1.5 px-4 py-2 text-sm sm:w-auto"
        style={{ backgroundColor: C.stamp, color: C.onAccent, fontFamily: F.body, fontWeight: 700, opacity: state.busy ? 0.6 : 1 }}>
        <ExternalLink size={15} /> {state.busy ? "Opening…" : "Open my portal"}
      </button>
      {state.email && <p role="status" className="mt-2 text-xs" style={{ color: C.green }}>Opening your portal — your sign-in code goes to {state.email}.</p>}
      {state.error && <p role="alert" className="mt-2 text-xs" style={{ color: C.carbon }}>{state.error}</p>}
    </section>
  );
}
