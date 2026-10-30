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

from .models import Rental, RentalEvent, add_months


# Raise the next rent invoice this many days before its period starts (its due date).
INVOICE_LEAD_DAYS = 3


class RentBillingError(Exception):
    pass


def period_months(start, end):
    """Whole months a billed period covers (a period ends the day before the
    same day-of-month N months on, so 1 Jan - 31 Mar is 3 months)."""
    after = end + timedelta(days=1)
    return max(1, (after.year - start.year) * 12 + after.month - start.month)


def _open_rent_invoices(rental):
    from sales.models import Invoice

    # cancelled rent invoices free their month to be billed again
    return rental.invoices.filter(source=Invoice.RENTAL, status__in=Invoice.OUTSTANDING)


def next_billing_period(rental):
    """(start, end) of the next month not yet invoiced, or None once the
    whole tenure has been billed. Months already paid plus months
    invoiced-but-unpaid are both "billed"."""
    billed = rental.months_paid + sum(
        period_months(inv.period_start, inv.period_end) if inv.period_start and inv.period_end else 1
        for inv in _open_rent_invoices(rental)
    )
    if billed >= rental.tenure_months:
        return None
    # one billing cycle (1/3/6/12 months), shorter if the tenure runs out first
    months = min(rental.payment_interval_months, rental.tenure_months - billed)
    start = add_months(rental.start, billed)
    end = add_months(rental.start, billed + months) - timedelta(days=1)
    return start, end


def rent_lines(rental, months=1):
    """One invoice line per device; qty is the number of months billed."""
    lines = list(rental.lines.select_related("asset"))
    if lines:
        return [
            {"description": f"Rent: {line.description} (S/N {line.asset.serial_number})", "qty": months, "price": line.monthly_fee}
            for line in lines
        ]
    return [{"description": f"Rent: {rental.product_label}", "qty": months, "price": rental.monthly_fee}]


def default_stock_point(rental):
    """The shop that issues automatic invoices: the one that issued this
    agreement's previous rent invoice, else the shop its first device came
    from, else the first shop on file."""
    from catalog.models import StockPoint

    last = rental.invoices.order_by("-date", "-id").first()
    if last:
        return last.stock_point
    for line in rental.lines.select_related("asset__source_stock_point"):
        if line.asset.source_stock_point_id:
            return line.asset.source_stock_point
    return StockPoint.objects.order_by("id").first()


def raise_rent_invoice(rental, *, stock_point, sent_by=None):
    """sent_by=None means the scheduler raised it automatically."""
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
            lines=rent_lines(rental, period_months(start, end)),
        )

    sender = (sent_by.get_full_name() or sent_by.username) if sent_by else None
    label = rental.agreement_code or rental.product_label
    months = period_months(start, end)
    text = (
        f"Hi {rental.party.name}, your rent invoice {invoice.code} for {label} "
        f"({start:%d %b} – {end:%d %b %Y}{f', {months} months' if months > 1 else ''}) is Rs {invoice.total}, due {start:%d %b %Y}. "
        f"{f'Sent by {sender}, ' if sender else ''}{settings.BUSINESS_NAME}."
    )
    Message.objects.create(party=rental.party, channel=Message.WHATSAPP, direction=Message.OUT, body=text)
    send_whatsapp(rental.party.phone, text)
    send_email(rental.party.email, f"Rent invoice {invoice.code}", text)
    return invoice


def on_rent_invoice_paid(invoice):
    """Count the paid month on the agreement. Due date = start of the
    billed month; paying after it counts as a late payment."""
    rental = Rental.objects.select_for_update().get(pk=invoice.rental_id)
    covered = period_months(invoice.period_start, invoice.period_end) if invoice.period_start and invoice.period_end else 1
    rental.months_paid = min(rental.tenure_months, rental.months_paid + covered)
    # last_payment anchors the "next payment due" date (one month later),
    # so it tracks the billed month rather than the day money arrived.
    if invoice.period_start and invoice.period_start > rental.last_payment:
        rental.last_payment = invoice.period_start
    if invoice.paid_on and invoice.period_start and invoice.paid_on > invoice.period_start:
        rental.late_count += 1
    if rental.status == Rental.APPROVED:
        rental.status = Rental.ACTIVE
    rental.save(update_fields=["months_paid", "last_payment", "late_count", "status"])


def send_due_rent_invoices(today=None, lead_days=INVOICE_LEAD_DAYS):
    """The recurring-payment scheduler. For every approved/active agreement
    with auto_invoice on, raise and send the next rent invoice once its
    period is within ``lead_days`` of starting. Idempotent: an invoice that
    is out (unpaid) counts as billed, so the same period is never invoiced
    twice, however often this runs. At most one invoice per agreement per
    run. Returns {"raised": [codes], "skipped": [(agreement, reason)]}."""
    today = today or timezone.localdate()
    raised, skipped = [], []
    rentals = Rental.objects.select_related("party").filter(
        status__in=(Rental.APPROVED, Rental.ACTIVE), auto_invoice=True,
    )
    for rental in rentals:
        period = next_billing_period(rental)
        if period is None or (period[0] - today).days > lead_days:
            continue
        stock_point = default_stock_point(rental)
        label = rental.agreement_code or f"#{rental.pk}"
        if stock_point is None:
            skipped.append((label, "no shop on file to issue the invoice"))
            continue
        try:
            raised.append(raise_rent_invoice(rental, stock_point=stock_point, sent_by=None).code)
        except RentBillingError as exc:
            skipped.append((label, str(exc)))
    return {"raised": raised, "skipped": skipped}


def set_payment_plan(rental, user, interval, auto_invoice):
    """Change the billing cycle / auto-invoicing for the invoices still to
    come. Invoices already raised keep their own period."""
    if interval not in dict(Rental.INTERVAL_CHOICES):
        raise RentBillingError("Choose 1, 3, 6 or 12 months.")
    with transaction.atomic():
        rental = Rental.objects.select_for_update().get(pk=rental.pk)
        if rental.status in (Rental.CANCELLED, Rental.CLOSED, Rental.REJECTED):
            raise RentBillingError("This agreement no longer bills.")
        before = {"interval": rental.payment_interval_months, "auto_invoice": rental.auto_invoice}
        rental.payment_interval_months = interval
        rental.auto_invoice = bool(auto_invoice)
        rental.save(update_fields=["payment_interval_months", "auto_invoice"])
        RentalEvent.objects.create(
            rental=rental, event_type=RentalEvent.PAYMENT_PLAN_CHANGED, actor=user,
            metadata={"before": before, "after": {"interval": interval, "auto_invoice": bool(auto_invoice)}},
        )
    return rental
