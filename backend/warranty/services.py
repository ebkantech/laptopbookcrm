"""
Warranty automation: warranties created when a sale is paid / a repair is
delivered, customer reminders before expiry, and the claim workflow.
Every customer-facing send is fail-soft (see crmbook_backend.notify).
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from branding import texts
from crmbook_backend.notify import send_email, send_whatsapp
from parties.models import Message
from .models import Warranty, WarrantyClaim

logger = logging.getLogger("crmbook.warranty")
EXPIRING_DAYS = 30
FINAL_DAYS = 7


def announce(warranty):
    """Email the terms to the customer and keep it on their message thread."""
    subject, body = texts.email("warranty_issued", item=warranty.item_label, start=f"{warranty.start_date:%d %b %Y}",
                                end=f"{warranty.end_date:%d %b %Y}", terms=warranty.terms_text)
    Message.objects.create(party=warranty.party, channel=Message.EMAIL, direction=Message.OUT, body=body)
    send_email(warranty.party.email, subject, body)


# ------------------------------------------------------------ automatic

def auto_sales_warranty(invoice):
    """A paid product sale gets its warranty without anyone remembering to raise it."""
    from sales.models import Invoice

    if invoice.source != Invoice.SALE or invoice.status != Invoice.PAID or not invoice.party_id:
        return None
    if Warranty.objects.filter(section=Warranty.SALES, invoice=invoice).exists():
        return None
    start = invoice.paid_on or invoice.date or timezone.localdate()
    def label(i):
        sns = [s.serial_number for s in i.serials.all()]
        return f"{i.label} (S/N {', '.join(sns)})" if sns else i.label

    # The guarantee written on the invoice wins: one warranty per item that
    # has one, for exactly those months. Items left blank get none.
    promised = [i for i in invoice.items.all() if i.warranty_months and i.item_kind != "discount"]
    if promised:
        from rentals.models import add_months

        made = None
        for item in promised:
            made = Warranty.objects.create(
                party=invoice.party, section=Warranty.SALES, item_label=label(item)[:160], invoice=invoice,
                start_date=start, end_date=add_months(start, item.warranty_months), auto_created=True,
                notes=f"Guarantee of {item.warranty_months} month{'s' if item.warranty_months != 1 else ''} as written on invoice {invoice.code}.")
            announce(made)
        return made

    days = int(getattr(settings, "WARRANTY_SALES_DAYS", 0) or 0)
    if days <= 0:
        return None

    names = ", ".join(label(i) for i in invoice.items.all() if i.item_kind != "discount") or invoice.code
    w = Warranty.objects.create(party=invoice.party, section=Warranty.SALES, item_label=names[:160], invoice=invoice,
                                start_date=start, end_date=start + timedelta(days=days), auto_created=True)
    announce(w)
    return w


def auto_repair_warranty(ticket):
    """A delivered repair gets its (shorter) workmanship warranty."""
    days = int(getattr(settings, "WARRANTY_REPAIR_DAYS", 0) or 0)
    inv = ticket.original_invoice
    if days <= 0 or not inv or inv.status not in ("Paid", "Refunded"):
        return None
    if Warranty.objects.filter(section=Warranty.REPAIR, repair_ticket=ticket).exists():
        return None
    start = inv.paid_on or inv.date or timezone.localdate()
    w = Warranty.objects.create(party=ticket.party, section=Warranty.REPAIR, item_label=f"Repair work on {ticket.brand} {ticket.model_name}"[:160],
                                repair_ticket=ticket, start_date=start, end_date=start + timedelta(days=days), auto_created=True)
    announce(w)
    return w


def safely(fn, obj):
    """Run an automation hook after the real action succeeded: it must never undo or fail it."""
    try:
        with transaction.atomic():
            return fn(obj)
    except Exception:
        logger.exception("warranty automation failed for %r", obj)
        return None


# ------------------------------------------------------------- reminders

def _reminder_text(w, days_left):
    when = "today" if days_left <= 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
    return texts.message("warranty_reminder", **_reminder_values(w, when))


def _reminder_values(w, when):
    return dict(customer=w.party.name, item=w.item_label, when=when, end=f"{w.end_date:%d %b %Y}")


def remind(w, today=None):
    """Tell the customer (WhatsApp + email) and keep it on their thread."""
    today = today or timezone.localdate()
    text = _reminder_text(w, (w.end_date - today).days)
    Message.objects.create(party=w.party, channel=Message.WHATSAPP, direction=Message.OUT, body=text)
    send_whatsapp(w.party.phone, text)
    days = (w.end_date - today).days
    send_email(w.party.email, *texts.email("warranty_reminder", **_reminder_values(
        w, "today" if days <= 0 else f"in {days} day{'s' if days != 1 else ''}")))
    return text


def send_due_reminders(today=None):
    """One reminder at <=30 days and one at <=7 days, each sent once. Safe to run daily or on demand."""
    from subscriptions import services as subscription_services

    if not subscription_services.can_write("warranty"):
        return 0
    today = today or timezone.localdate()
    sent = 0
    for w in Warranty.objects.select_related("party").filter(end_date__gte=today, end_date__lte=today + timedelta(days=EXPIRING_DAYS)):
        left = (w.end_date - today).days
        field = "reminded_7_at" if left <= FINAL_DAYS else "reminded_30_at"
        if getattr(w, field) or (field == "reminded_30_at" and w.reminded_7_at):
            continue
        remind(w, today)
        now = timezone.now()
        setattr(w, field, now)
        if field == "reminded_7_at" and not w.reminded_30_at:
            w.reminded_30_at = now
        w.save(update_fields=["reminded_30_at", "reminded_7_at"])
        sent += 1
    return sent


# ---------------------------------------------------------------- claims

def next_claim_code():
    top = 0
    for code in WarrantyClaim.objects.filter(code__regex=r"^WC-[0-9]+$").values_list("code", flat=True):
        top = max(top, int(code[3:]))
    return f"WC-{top + 1:04d}"


def _tell(claim, key, **values):
    w = claim.warranty
    values = {"claim": claim.code, "item": w.item_label, **values}
    text = texts.message(key, **values)
    Message.objects.create(party=w.party, channel=Message.WHATSAPP, direction=Message.OUT, body=text)
    send_whatsapp(w.party.phone, text)
    send_email(w.party.email, *texts.email(key, **values))


@transaction.atomic
def raise_claim(warranty, user, issue, repair_ticket=None):
    issue = (issue or "").strip()
    if len(issue) < 5:
        raise ValidationError({"issue": "Describe what is wrong."})
    if warranty.status == "Expired":
        raise ValidationError({"warranty": f"This warranty ended on {warranty.end_date:%d %b %Y}, so a claim can't be raised."})
    if repair_ticket and repair_ticket.party_id != warranty.party_id:
        raise ValidationError({"repair_ticket": "That repair job belongs to a different customer."})
    claim = WarrantyClaim.objects.create(code=next_claim_code(), warranty=warranty, issue=issue[:2000],
                                         repair_ticket=repair_ticket, raised_by=user)
    _tell(claim, "warranty_claim_logged")
    return claim


@transaction.atomic
def decide_claim(claim, user, decision, note=""):
    claim = WarrantyClaim.objects.select_for_update().get(pk=claim.pk)
    if claim.status != WarrantyClaim.OPEN:
        raise ValidationError({"detail": f"This claim is already {claim.get_status_display().lower()}."})
    note = (note or "").strip()
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose approve or reject."})
    if decision == "reject" and not note:
        raise ValidationError({"note": "Give the customer the reason it was rejected."})
    claim.status = WarrantyClaim.APPROVED if decision == "approve" else WarrantyClaim.REJECTED
    claim.decision_note, claim.decided_by, claim.decided_at = note[:300], user, timezone.now()
    claim.save(update_fields=["status", "decision_note", "decided_by", "decided_at"])
    if decision == "approve":
        _tell(claim, "warranty_claim_approved")
    else:
        _tell(claim, "warranty_claim_rejected", reason=note)
    return claim


@transaction.atomic
def resolve_claim(claim, user, resolution, cost, note="", repair_ticket=None):
    claim = WarrantyClaim.objects.select_for_update().get(pk=claim.pk)
    if claim.status != WarrantyClaim.APPROVED:
        raise ValidationError({"detail": "Approve the claim before resolving it."})
    if resolution not in dict(WarrantyClaim.RESOLUTION_CHOICES):
        raise ValidationError({"resolution": "Choose repaired, replaced, refunded or other."})
    try:
        cost = int(cost or 0)
    except (TypeError, ValueError):
        raise ValidationError({"cost": "Enter the cost as a whole number (0 if none)."})
    if not 0 <= cost <= 10_000_000:
        raise ValidationError({"cost": "Enter a cost between 0 and 1,00,00,000."})
    if repair_ticket:
        if repair_ticket.party_id != claim.warranty.party_id:
            raise ValidationError({"repair_ticket": "That repair job belongs to a different customer."})
        claim.repair_ticket = repair_ticket
    claim.status, claim.resolution, claim.cost = WarrantyClaim.RESOLVED, resolution, cost
    claim.resolution_note, claim.resolved_at = (note or "")[:300], timezone.now()
    claim.save(update_fields=["status", "resolution", "cost", "resolution_note", "resolved_at", "repair_ticket"])
    _tell(claim, "warranty_claim_done", resolution=claim.get_resolution_display().lower())
    return claim
