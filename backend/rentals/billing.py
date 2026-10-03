"""
Monthly rent invoicing. The rentals module decides *what* to bill (the
next unbilled month of an agreement) and raises it as a sales.Invoice
(source=rental) with its own INV number, dated the day it is sent.
Payment then happens in Sales & Invoices; on_rent_invoice_paid() moves
the agreement's own counters (months paid, last payment, late count).
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from crmbook_backend.notify import send_email, send_whatsapp
from parties.models import Message

from .models import Rental, add_months


class RentBillingError(Exception):
    pass


def _open_rent_invoices(rental):
    from sales.models import Invoice

    return rental.invoices.filter(source=Invoice.RENTAL).exclude(status=Invoice.PAID)


def next_billing_period(rental):
    """(start, end) of the next month not yet invoiced, or None once the
    whole tenure has been billed. Months already paid plus months
    invoiced-but-unpaid are both "billed"."""
    billed = rental.months_paid + _open_rent_invoices(rental).count()
    if billed >= rental.tenure_months:
        return None
    start = add_months(rental.start, billed)
    end = add_months(rental.start, billed + 1) - timedelta(days=1)
    return start, end


def rent_lines(rental):
    lines = list(rental.lines.select_related("asset"))
    if lines:
        return [
            {"description": f"Rent: {line.description} (S/N {line.asset.serial_number})", "qty": 1, "price": line.monthly_fee}
            for line in lines
        ]
    return [{"description": f"Rent: {rental.product_label}", "qty": 1, "price": rental.monthly_fee}]


def raise_rent_invoice(rental, *, stock_point, sent_by):
    from sales.models import Invoice
    from sales.services import create_invoice

    if rental.status not in (Rental.APPROVED, Rental.ACTIVE):
        raise RentBillingError("Rent can only be invoiced on an approved or active agreement.")
    with transaction.atomic():
        # lock the agreement so two clicks can't bill the same month twice
        Rental.objects.select_for_update().get(pk=rental.pk)
        period = next_billing_period(rental)
        if period is None:
            raise RentBillingError("Every month of this agreement's tenure has already been invoiced.")
        start, end = period
        invoice = create_invoice(
            source=Invoice.RENTAL, rental=rental, party=rental.party, stock_point=stock_point,
            date=timezone.localdate(), status=Invoice.LINK_SENT, period_start=start, period_end=end,
            lines=rent_lines(rental),
        )

    sender = sent_by.get_full_name() or sent_by.username
    label = rental.agreement_code or rental.product_label
    text = (
        f"Hi {rental.party.name}, your rent invoice {invoice.code} for {label} "
        f"({start:%d %b} – {end:%d %b %Y}) is Rs {invoice.total}, due {start:%d %b %Y}. "
        f"Sent by {sender}, {settings.BUSINESS_NAME}."
    )
    Message.objects.create(party=rental.party, channel=Message.WHATSAPP, direction=Message.OUT, body=text)
    send_whatsapp(rental.party.phone, text)
    send_email(rental.party.email, f"Rent invoice {invoice.code}", text)
    return invoice


def on_rent_invoice_paid(invoice):
    """Count the paid month on the agreement. Due date = start of the
    billed month; paying after it counts as a late payment."""
    rental = Rental.objects.select_for_update().get(pk=invoice.rental_id)
    rental.months_paid = min(rental.tenure_months, rental.months_paid + 1)
    # last_payment anchors the "next payment due" date (one month later),
    # so it tracks the billed month rather than the day money arrived.
    if invoice.period_start and invoice.period_start > rental.last_payment:
        rental.last_payment = invoice.period_start
    if invoice.paid_on and invoice.period_start and invoice.paid_on > invoice.period_start:
        rental.late_count += 1
    if rental.status == Rental.APPROVED:
        rental.status = Rental.ACTIVE
    rental.save(update_fields=["months_paid", "last_payment", "late_count", "status"])
