"""
UPI payment links for sales invoices.

Flow (see InvoiceViewSet.upi_check / send_upi_link):
  1. check_upi_linked(phone) -- is this mobile number registered with UPI?
     If not, staff asks the customer for another number and checks again.
  2. create_upi_link(...) -- creates a UPI-only payment link for the
     invoice amount and has it texted to that number.
  3. The provider calls back (razorpay_webhook) when it's paid, or staff
     presses "Check payment status"; either way mark_link_paid() settles
     the invoice with the UPI transaction reference.

Two independent provider switches, same shape as notify.py's WhatsApp one:

  PAYMENT_PROVIDER=sandbox | razorpay      (default sandbox)
    sandbox  -- no money moves; the link is a placeholder and staff can
                "simulate payment" to exercise the paid path end to end.
    razorpay -- Razorpay Payment Links with upi_link=true (UPI-only), and
                Razorpay's own SMS to the customer (notify.sms). Needs
                RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, and for automatic
                paid-status updates RAZORPAY_WEBHOOK_SECRET plus a webhook
                in the Razorpay dashboard pointing at
                /api/payments/razorpay-webhook/ for "payment_link.paid".

  UPI_LOOKUP_PROVIDER=sandbox | none       (default sandbox)
    Razorpay cannot tell whether a mobile number has UPI -- that needs a
    separate mobile-to-UPI lookup service. Until one is chosen and wired
    in here, "none" reports the check as not possible (status "unknown")
    and the staff member must confirm with the customer; that
    confirmation is stored on the PaymentLink.
    sandbox -- valid-looking Indian mobile numbers count as UPI-linked,
               except ones ending in 0, so the "not linked, ask for
               another number" path can be tried in development.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request

from django.utils import timezone

logger = logging.getLogger("crmbook.payments")

LINKED, NOT_LINKED, UNKNOWN = "linked", "not_linked", "unknown"


def normalize_mobile(phone):
    """Indian mobile number as 10 digits, or None if it isn't one."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return digits


def mask(phone10):
    return f"******{phone10[-4:]}"


def payment_provider():
    return os.environ.get("PAYMENT_PROVIDER", "sandbox")


# ------------------------------------------------------------------ #
#  Step 1: is the number on UPI?
# ------------------------------------------------------------------ #

def check_upi_linked(phone10):
    """Returns {"status": linked | not_linked | unknown, "reason": str | None}."""
    provider = os.environ.get("UPI_LOOKUP_PROVIDER", "sandbox")
    if provider == "sandbox":
        linked = not phone10.endswith("0")
        logger.info("[UPI lookup:sandbox -- simulated] phone=%s linked=%s", mask(phone10), linked)
        return {
            "status": LINKED if linked else NOT_LINKED,
            "reason": None if linked else "No UPI account found for this number (sandbox rule: numbers ending in 0).",
        }
    return {
        "status": UNKNOWN,
        "reason": "Automatic UPI check isn't set up -- confirm with the customer that this number has UPI (e.g. GPay/PhonePe/Paytm).",
    }


# ------------------------------------------------------------------ #
#  Step 2: create + send the link
# ------------------------------------------------------------------ #

class PaymentProviderError(Exception):
    pass


def _razorpay_request(method, path, payload=None):
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise PaymentProviderError("Razorpay isn't configured -- set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.razorpay.com/v1{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        logger.error("[Razorpay] %s %s -> %s %s", method, path, e.code, body)
        try:
            detail = json.loads(body).get("error", {}).get("description") or body
        except ValueError:
            detail = body
        raise PaymentProviderError(f"Razorpay error: {detail}") from e
    except urllib.error.URLError as e:
        raise PaymentProviderError(f"Couldn't reach Razorpay: {e.reason}") from e


def create_upi_link(invoice, phone10, sent_by_name, description):
    """
    Create a UPI-only payment link and have it texted to phone10.
    Returns {"provider_link_id", "url", "sms_sent_by_provider"}.
    """
    provider = payment_provider()
    if provider == "razorpay":
        party = invoice.party
        data = _razorpay_request("POST", "/payment_links", {
            "amount": invoice.total * 100,  # paise
            "currency": "INR",
            "upi_link": True,
            "description": description[:2048],
            "reference_id": f"{invoice.code}-{timezone.now():%Y%m%d%H%M%S}",
            "customer": {"name": party.name, "contact": f"+91{phone10}", **({"email": party.email} if party.email else {})},
            "notify": {"sms": True, "email": False},
            "reminder_enable": True,
            "notes": {"invoice": invoice.code, "sent_by": sent_by_name},
        })
        return {"provider_link_id": data["id"], "url": data["short_url"], "sms_sent_by_provider": True}

    # sandbox: nothing leaves the building
    token = hashlib.sha256(f"{invoice.pk}-{phone10}-{timezone.now().isoformat()}".encode()).hexdigest()[:12]
    print(f"\n[UPI link:sandbox -- simulated, no SMS sent] to=+91{phone10}\n{description}\n{'-' * 79}")
    return {"provider_link_id": f"sandbox_{token}", "url": f"https://sandbox.invalid/upi/{token}", "sms_sent_by_provider": False}


def fetch_link_payment(link):
    """
    Ask the provider whether the link has been paid. Returns
    {"paid": bool, "payment_id": str | None, "rrn": str | None}.
    """
    if link.provider != "razorpay":
        return {"paid": False, "payment_id": None, "rrn": None}
    data = _razorpay_request("GET", f"/payment_links/{link.provider_link_id}")
    if data.get("status") != "paid":
        return {"paid": False, "payment_id": None, "rrn": None}
    payments = data.get("payments") or []
    captured = next((p for p in payments if p.get("status") == "captured"), payments[0] if payments else {})
    return {"paid": True, "payment_id": captured.get("payment_id"), "rrn": None}


def cancel_provider_link(link):
    """Best effort: stop the customer paying a link for a cancelled
    invoice. A failure is logged, not raised -- our own record is already
    cancelled, and a payment that still slips through is visible in the
    provider dashboard."""
    if link.provider != "razorpay" or not link.provider_link_id:
        return
    try:
        _razorpay_request("POST", f"/payment_links/{link.provider_link_id}/cancel", {})
    except PaymentProviderError:
        logger.exception("[Razorpay] couldn't cancel payment link %s", link.provider_link_id)


def verify_razorpay_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ------------------------------------------------------------------ #
#  Step 3: paid
# ------------------------------------------------------------------ #

def mark_link_paid(link, payment_id=None, rrn=None):
    """Settle the invoice from a confirmed UPI payment. Idempotent."""
    from .models import Invoice, PaymentLink

    if link.status == PaymentLink.PAID:
        return False
    now = timezone.now()
    link.status = PaymentLink.PAID
    link.paid_at = now
    link.provider_payment_id = payment_id or ""
    link.save(update_fields=["status", "paid_at", "provider_payment_id"])

    invoice = link.invoice
    if invoice.status in Invoice.OUTSTANDING:  # never revive a cancelled invoice
        reference = " / ".join(x for x in [f"UPI RRN {rrn}" if rrn else "", payment_id or ""] if x) or f"UPI link {link.provider_link_id}"
        invoice.status = Invoice.PAID
        invoice.pay_method = "UPI"
        invoice.payment_reference = reference[:80]
        invoice.paid_on = timezone.localdate()
        invoice.settled_by = None  # confirmed by the payment provider, not a person
        invoice.save(update_fields=["status", "pay_method", "payment_reference", "paid_on", "settled_by"])
        from .services import on_invoice_paid

        on_invoice_paid(invoice)
    # any other open links for the same invoice are now moot
    invoice.payment_links.exclude(pk=link.pk).filter(status=PaymentLink.SENT).update(status=PaymentLink.CANCELLED)
    return True
