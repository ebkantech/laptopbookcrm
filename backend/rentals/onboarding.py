"""
The order a new rental follows:

  1. Customer: registered, or an existing one chosen.
  2. KYC: verified by staff against the originals before an agreement can be
     created. Aadhaar and PAN for an individual, PAN for a business or dealer
     (which has no Aadhaar).
  3. Devices: chosen from what's available, when the agreement is created.
  4. Agreement: raises the security deposit and the advance, one month's rent
     each. The advance covers month 1, so billing carries on from month 2.
  5. Customer approval, once device details are complete (or an Admin
     approves on the customer's behalf).
  6. Payment: both invoices are collected in Sales & Invoices.
  7. Portal: once approved, verified and paid, the customer can sign in and
     follow the laptop before it reaches them.
  8. Checkout: staff hand over the device. Only now is it rented and the
     agreement active.

Until checkout the agreement is "waiting for handover". Only agreements created
after this was added carry requires_onboarding, so older ones work as they
always did. A renewal skips the deposit: the original stays held on the earlier
agreement.

The deposit is the customer's money, not income, so it is flagged
(Invoice.is_deposit): it reaches the cash and bank books when paid, and stays
out of revenue, rent counts and profit. It's returned with an ordinary refund
on its invoice in Sales & Invoices.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from parties.models import Party, PartyIdDocument

from .billing import default_stock_point, rent_lines
from .models import Rental, RentalAsset, RentalEvent, add_months

OPEN_STATUSES = (Rental.DRAFT, Rental.PENDING_APPROVAL, Rental.REJECTED)
BEFORE_CHECKOUT = (*OPEN_STATUSES, Rental.APPROVED)


def _live(rental, **kinds):
    from sales.models import Invoice

    return rental.invoices.exclude(status=Invoice.CANCELLED).filter(source=Invoice.RENTAL, **kinds).order_by("-id").first()


def deposit_invoice(rental):
    return _live(rental, is_deposit=True)


def advance_invoice(rental):
    return _live(rental, is_advance=True, is_deposit=False)


def _deposit_due(rental):
    """A renewal has no deposit of its own; every other new agreement does."""
    return rental.requires_onboarding and not rental.renews_id


def ensure_invoices(rental):
    """Raise whichever of the two invoices is missing (first time, or after
    one was cancelled). Returns the ones raised, for send_invoices."""
    from datetime import timedelta

    from sales.models import Invoice
    from sales.services import create_invoice

    if not rental.requires_onboarding:
        return []
    stock_point = default_stock_point(rental)
    if stock_point is None:
        raise ValidationError({"detail": "There's no shop on file to issue this agreement's invoices."})
    label = rental.agreement_code or rental.product_label
    today = timezone.localdate()
    common = dict(source=Invoice.RENTAL, rental=rental, party=rental.party, stock_point=stock_point,
                  date=today, due_date=today, status=Invoice.LINK_SENT)
    raised = []
    if _deposit_due(rental) and deposit_invoice(rental) is None:
        raised.append(create_invoice(is_deposit=True, lines=[
            {"description": f"Security deposit (refundable): {label}", "qty": 1, "price": rental.total_monthly_fee},
        ], **common))
    if advance_invoice(rental) is None:
        raised.append(create_invoice(is_advance=True, period_start=rental.start,
                                     period_end=add_months(rental.start, 1) - timedelta(days=1),
                                     lines=rent_lines(rental, 1), **common))
    return raised


def send_invoices(rental, invoices, user):
    """Tell the customer about the deposit and advance, with their payment links."""
    from django.conf import settings

    from crmbook_backend.notify import send_email, send_whatsapp
    from parties.models import Message
    from sales.payments import pay_note

    if not invoices:
        return
    label = rental.agreement_code or rental.product_label
    parts = [f"{'Security deposit' if invoice.is_deposit else 'Advance rent'} invoice {invoice.code}: "
             f"Rs {invoice.total}.{pay_note(invoice, user)}" for invoice in invoices]
    text = f"Hi {rental.party.name}, for your rental {label}: {' '.join(parts)} {settings.BUSINESS_NAME}."
    Message.objects.create(party=rental.party, channel=Message.WHATSAPP, direction=Message.OUT, body=text)
    send_whatsapp(rental.party.phone, text)
    send_email(rental.party.email, f"Rental invoices for {label}", text)


def sync_amounts(rental):
    """If the rent changes before payment, the unpaid deposit and advance follow it."""
    from sales.models import Invoice, InvoiceItem
    from sales.payments import replace_invoice_link

    if not rental.requires_onboarding:
        return
    deposit = deposit_invoice(rental)
    if deposit and deposit.status in Invoice.OUTSTANDING and deposit.total != rental.total_monthly_fee:
        InvoiceItem.objects.filter(invoice=deposit).update(price=rental.total_monthly_fee)
        replace_invoice_link(deposit)
    advance = advance_invoice(rental)
    if advance and advance.status in Invoice.OUTSTANDING and advance.total != rental.total_monthly_fee:
        advance.items.all().delete()
        for line in rent_lines(rental, 1):
            InvoiceItem.objects.create(invoice=advance, **line)
        replace_invoice_link(advance)


def _invoice_row(invoice):
    if invoice is None:
        return None
    return {"id": invoice.id, "code": invoice.code, "status": invoice.status, "total": invoice.total,
            "refunded": invoice.refunded_total, "paid_on": invoice.paid_on}


def _paid(invoice):
    from sales.models import Invoice

    return bool(invoice and invoice.status == Invoice.PAID)


def needs_aadhaar(party):
    return party.customer_classification == Party.INDIVIDUAL


def _id_state(party, id_type):
    """verified, recorded (still to be checked against the original) or missing."""
    states = [d.status for d in party.id_documents.all() if d.id_type == id_type]
    if PartyIdDocument.VERIFIED in states:
        return "verified"
    return "recorded" if PartyIdDocument.FORMAT_OK in states or PartyIdDocument.NOT_VERIFIED in states else "missing"


def _id_problem(state, label):
    if state == "verified":
        return None
    return f"Verify the customer's {label} against the original." if state == "recorded" else f"Record the customer's {label}."


def id_problems(party):
    """What's still needed before this customer's KYC counts as verified."""
    problems = []
    if needs_aadhaar(party):
        problems.append(_id_problem(_id_state(party, PartyIdDocument.AADHAAR), "Aadhaar"))
    problems.append(_id_problem(_id_state(party, PartyIdDocument.PAN), "PAN"))
    return [problem for problem in problems if problem]


def require_kyc(party):
    """Called before an agreement is created."""
    problems = id_problems(party)
    if problems:
        raise ValidationError({"detail": f"Verify the customer's KYC before creating an agreement. {' '.join(problems)}"})


def status(rental):
    """The checklist the rental card shows, and what each next step still needs."""
    if not rental.requires_onboarding:
        return {"required": False}
    deposit, advance = deposit_invoice(rental), advance_invoice(rental)
    party = rental.party
    aadhaar_needed = needs_aadhaar(party)
    aadhaar, pan = _id_state(party, PartyIdDocument.AADHAAR), _id_state(party, PartyIdDocument.PAN)
    kyc = id_problems(party)
    payment = []
    if _deposit_due(rental) and not deposit:
        payment.append("The security deposit invoice was cancelled. Raise it again.")
    elif _deposit_due(rental) and not _paid(deposit):
        payment.append(f"Collect the security deposit (invoice {deposit.code}).")
    if not advance:
        payment.append("The advance rent invoice was cancelled. Raise it again.")
    elif not _paid(advance):
        payment.append(f"Collect the advance rent (invoice {advance.code}).")
    checked_out = bool(rental.checked_out_at)
    approved = rental.status == Rental.APPROVED
    checkout_blocking = [*kyc, *payment]
    if rental.status in OPEN_STATUSES:
        checkout_blocking.append("Get the customer's approval.")
    return {
        "required": True,
        "deposit_required": _deposit_due(rental),
        "deposit": _invoice_row(deposit),
        "advance": _invoice_row(advance),
        "needs_aadhaar": aadhaar_needed,
        "aadhaar": aadhaar,
        "pan": pan,
        "kyc_verified": not kyc,
        "paid": not payment,
        "approved": approved or checked_out,
        "checked_out": checked_out,
        "checked_out_at": rental.checked_out_at,
        "ready_for_checkout": approved and not checked_out and not checkout_blocking,
        "waiting_for_handover": rental.status in BEFORE_CHECKOUT and not checked_out and bool(checkout_blocking),
        "blocking": checkout_blocking,
    }


def portal_ready(rental):
    """Whether this agreement lets its customer sign in: approved, verified and paid."""
    if not rental.requires_onboarding or rental.checked_out_at or rental.status == Rental.ACTIVE:
        return True
    return rental.status == Rental.APPROVED and not status(rental)["blocking"]


def laptop_status(rental):
    """Where the laptop is, in the customer's words."""
    if rental.status in (Rental.CANCELLED, Rental.REJECTED):
        return {"key": "cancelled", "label": "Cancelled", "detail": "This agreement did not go ahead."}
    if rental.status == Rental.CLOSED:
        return {"key": "returned", "label": "Returned", "detail": "The laptop is back with us. Thank you."}
    if rental.status == Rental.ACTIVE or rental.checked_out_at or not rental.requires_onboarding:
        return {"key": "with_you", "label": "With you", "detail": "The laptop has been handed over to you.",
                "handed_over_on": rental.checked_out_at.date() if rental.checked_out_at else None}
    if rental.status == Rental.APPROVED and not status(rental)["blocking"]:
        return {"key": "ready", "label": "Ready for handover",
                "detail": "Your laptop is ready. Our team will arrange the handover."}
    return {"key": "preparing", "label": "Being prepared",
            "detail": "We are finishing your verification and payments before the laptop is prepared."}


def require_ready(rental):
    """Called before an approval link is issued or an Admin approves on the customer's behalf."""
    if rental.requires_onboarding:
        problems = id_problems(rental.party)
        if problems:
            raise ValidationError({"detail": " ".join(problems)})


def handover_locked_message(rental):
    """Device details can't be recorded for a customer whose KYC no longer stands."""
    if rental.requires_onboarding and id_problems(rental.party):
        return "Waiting for handover: devices can't be prepared until the customer's ID is verified."
    return None


def awaiting_checkout(rental):
    """An approved agreement whose device hasn't gone out: no rent yet."""
    return rental.requires_onboarding and rental.status == Rental.APPROVED and not rental.checked_out_at


@transaction.atomic
def checkout(rental, user):
    """Hand the device to the customer: the last step before the rental is live."""
    rental = Rental.objects.select_for_update().select_related("party").get(pk=rental.pk)
    if not awaiting_checkout(rental):
        raise ValidationError({"detail": "Only an approved agreement waiting for handover can be checked out."})
    blocking = status(rental)["blocking"]
    if blocking:
        raise ValidationError({"detail": " ".join(blocking)})
    rental.checked_out_at, rental.checked_out_by = timezone.now(), user
    rental.status = Rental.ACTIVE
    rental.save(update_fields=["checked_out_at", "checked_out_by", "status"])
    RentalAsset.objects.filter(rental_lines__rental=rental).update(status=RentalAsset.RENTED)
    RentalEvent.objects.create(rental=rental, event_type=RentalEvent.DEVICE_CHECKED_OUT, actor=user)
    return rental


@transaction.atomic
def cancel_unpaid(rental, user, reason):
    """When an agreement is cancelled, nothing should stay payable. Money already
    collected isn't touched here: staff refund it from Sales & Invoices."""
    from sales.models import Invoice
    from sales.services import cancel_invoice

    for invoice in rental.invoices.filter(status__in=Invoice.OUTSTANDING, source=Invoice.RENTAL):
        if invoice.is_deposit or invoice.is_advance:
            cancel_invoice(invoice, user, f"Agreement cancelled: {reason}"[:200])
