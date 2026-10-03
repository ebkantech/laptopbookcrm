"""
The one way invoices get raised and paid, whichever module they come
from. Sales, repairs and rentals all call create_invoice(); every
payment path (manual settle, UPI link webhook/refresh) ends in
on_invoice_paid(), which tells the originating module.
"""
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

INVOICE_PREFIX = "INV-"
_CODE_RE = re.compile(r"^INV-(\d+)$")
# Continue on from the numbering the business already used.
FIRST_INVOICE_NUMBER = 3321


def next_invoice_code():
    from .models import Invoice

    highest = FIRST_INVOICE_NUMBER - 1
    for code in Invoice.objects.filter(code__regex=r"^INV-[0-9]+$").values_list("code", flat=True):
        highest = max(highest, int(_CODE_RE.match(code).group(1)))
    return f"{INVOICE_PREFIX}{highest + 1}"


def create_invoice(*, lines, **fields):
    """
    Create an invoice with the next INV number and its lines.
    lines: dicts with qty, price and either variant or description.
    Retries if two invoices race for the same number.
    """
    from .models import Invoice, InvoiceItem

    if "due_date" not in fields:
        if fields.get("source") == Invoice.RENTAL and fields.get("period_start"):
            fields["due_date"] = fields["period_start"]
        else:
            fields["due_date"] = fields["date"] + timedelta(days=settings.INVOICE_DUE_DAYS)
    for attempt in range(5):
        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(code=next_invoice_code(), **fields)
                for line in lines:
                    InvoiceItem.objects.create(invoice=invoice, **line)
                return invoice
        except IntegrityError:
            if attempt == 4:
                raise
    raise RuntimeError("unreachable")


def on_invoice_paid(invoice):
    """Called once an invoice has just been marked paid, by any route."""
    from accounting.posting import post_invoice_payment

    from .models import Invoice

    post_invoice_payment(invoice)

    if invoice.source == Invoice.REPAIR and invoice.repair_ticket_id:
        from repairs.billing import on_repair_invoice_paid

        on_repair_invoice_paid(invoice)
    if invoice.source == Invoice.RENTAL and invoice.rental_id:
        from rentals.billing import on_rent_invoice_paid

        on_rent_invoice_paid(invoice)


def mark_overdue():
    """Unpaid invoices past their due date become Overdue. One cheap UPDATE,
    run whenever invoice figures are read (list, dashboard, reports), so
    no scheduler is needed."""
    from .models import Invoice

    return Invoice.objects.filter(status=Invoice.LINK_SENT, due_date__lt=timezone.localdate()).update(status=Invoice.OVERDUE)


class CancelError(Exception):
    pass


@transaction.atomic
def cancel_invoice(invoice, user, reason):
    """
    Cancel an invoice raised by mistake. Only unpaid invoices -- a paid one
    needs a refund, not a cancellation. Effects by source:
      sale   -> the units go back on the shelf they were sold from
      rental -> that month is free to be billed again
      repair -> the job can be invoiced again
    Any open payment link is cancelled too, so the customer can't pay it.
    """
    from catalog.models import Stock

    from .models import Invoice, PaymentLink

    reason = (reason or "").strip()
    if not reason:
        raise CancelError("Give a reason for cancelling this invoice.")
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == Invoice.CANCELLED:
        raise CancelError("This invoice is already cancelled.")
    if invoice.status == Invoice.PAID:
        raise CancelError("A paid invoice can't be cancelled -- it needs a refund instead.")
    if invoice.source == Invoice.SALE:
        for item in invoice.items.filter(variant__isnull=False):
            updated = Stock.objects.filter(variant_id=item.variant_id, stock_point_id=invoice.stock_point_id).update(quantity=F("quantity") + item.qty)
            if not updated:
                Stock.objects.create(variant_id=item.variant_id, stock_point_id=invoice.stock_point_id, quantity=item.qty)
    for link in invoice.payment_links.filter(status=PaymentLink.SENT):
        from .payments import cancel_provider_link

        cancel_provider_link(link)
    invoice.payment_links.filter(status=PaymentLink.SENT).update(status=PaymentLink.CANCELLED)
    update = ["status", "cancel_reason", "cancelled_by", "cancelled_at"]
    if invoice.repair_reopen_id:
        # free the follow-up visit so it can be invoiced again (one invoice
        # per visit); the ticket link keeps the history
        invoice.repair_reopen = None
        update.append("repair_reopen")
    invoice.status = Invoice.CANCELLED
    invoice.cancel_reason = reason[:200]
    invoice.cancelled_by = user
    invoice.cancelled_at = timezone.now()
    invoice.save(update_fields=update)
    return invoice
