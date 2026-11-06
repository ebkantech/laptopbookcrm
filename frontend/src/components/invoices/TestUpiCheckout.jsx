import { useEffect, useState } from "react";
import { FlaskConical, RefreshCw } from "lucide-react";
import { C, F } from "../../lib/theme";
import { api } from "../../lib/api";
import { ErrorNote } from "../Atoms";

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";
let checkoutScript = null;

// Razorpay's Checkout script, loaded once and only when it's needed.
function loadCheckout() {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  if (!checkoutScript) {
    checkoutScript = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = CHECKOUT_SRC;
      s.async = true;
      s.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error("Razorpay Checkout didn't load.")));
      s.onerror = () => reject(new Error("Couldn't load Razorpay Checkout -- check the connection (or a content blocker)."));
      document.body.appendChild(s);
    }).catch((e) => {
      checkoutScript = null; // let the next click try again
      throw e;
    });
  }
  return checkoutScript;
}

/*
 * Razorpay Test Mode only: pay this invoice through Standard Checkout
 * (UPI test ID success@razorpay) to try the paid path, since UPI-only
 * payment links don't exist in Test Mode. Shown only when the backend
 * says the configured key is an rzp_test_ key; the invoice is marked
 * paid by the server after it has verified the payment with Razorpay.
 */
export default function TestUpiCheckout({ invoice, onChanged }) {
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(null); // a Checkout result still to verify

  useEffect(() => {
    let live = true;
    api.get("/invoices/test-checkout-config/")
      .then((res) => live && setAvailable(!!res.available))
      .catch(() => live && setAvailable(false));
    return () => { live = false; };
  }, []);

  const verify = async (result) => {
    setBusy("verify");
    setError("");
    try {
      const updated = await api.post(`/invoices/${invoice.id}/test-checkout-verify/`, result);
      setPending(null);
      onChanged(updated);
      setNote(`Test payment verified with Razorpay — invoice marked paid (${updated.pay_method}).`);
    } catch (e) {
      setPending(result);
      setError(`Payment not recorded: ${e.body?.detail || e.message}`);
    } finally {
      setBusy("");
    }
  };

  const start = async () => {
    setBusy("open");
    setError("");
    setNote("");
    setPending(null);
    try {
      const [Razorpay, order] = await Promise.all([
        loadCheckout(),
        api.post(`/invoices/${invoice.id}/test-checkout-order/`, {}),
      ]);
      const checkout = new Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: order.name,
        description: order.description,
        // documented preselection; Razorpay applies it only when contact and email are prefilled too
        prefill: { ...order.prefill, method: "upi" },
        notes: { invoice: invoice.code },
        handler: (result) => verify({
          razorpay_order_id: result.razorpay_order_id,
          razorpay_payment_id: result.razorpay_payment_id,
          razorpay_signature: result.razorpay_signature,
        }),
        modal: {
          ondismiss: () => {
            setBusy((b) => (b === "checkout" ? "" : b));
            setNote((n) => n || "Checkout closed — no payment recorded.");
          },
        },
      });
      checkout.on("payment.failed", (res) => {
        setError(`Payment failed: ${res.error?.description || "declined"} — the invoice is unchanged.`);
      });
      setBusy("checkout");
      checkout.open();
    } catch (e) {
      setBusy("");
      setError(e.body?.detail || e.message);
    }
  };

  if (!available) return null;

  return (
    <div className="mt-3 pt-2" style={{ borderTop: `1px dashed ${C.rule}` }}>
      <p className="text-xs" style={{ fontFamily: F.body, color: C.amber }}>
        Razorpay Test Mode — no real money. Choose UPI in Checkout and pay with the test UPI ID <b style={{ fontFamily: F.mono }}>success@razorpay</b> (or <span style={{ fontFamily: F.mono }}>failure@razorpay</span> to try a failure).
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button onClick={start} disabled={!!busy} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px dashed ${C.amber}`, fontFamily: F.body, color: C.amber, opacity: busy ? 0.6 : 1 }}>
          <FlaskConical size={11} /> {busy === "open" ? "Opening…" : busy === "checkout" ? "Checkout open…" : busy === "verify" ? "Verifying…" : "Test UPI Payment"}
        </button>
        {pending && (
          <button onClick={() => verify(pending)} disabled={!!busy} className="flex items-center gap-1 px-2 py-1 text-xs" style={{ border: `1px solid ${C.rule}`, fontFamily: F.body, color: C.ink }}>
            <RefreshCw size={11} /> Verify again
          </button>
        )}
      </div>
      {note && <p className="mt-2 text-xs" style={{ fontFamily: F.body, color: C.green }}>{note}</p>}
      <ErrorNote message={error} />
    </div>
  );
}
