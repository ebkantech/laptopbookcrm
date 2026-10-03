"""
The one way invoices get raised and paid, whichever module they come
from. Sales, repairs and rentals all call create_invoice(); every
payment path (manual settle, UPI link webhook/refresh) ends in
on_invoice_paid(), which tells the originating module.
"""
import re

from django.db import IntegrityError, transaction

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
    from .models import Invoice

    if invoice.source == Invoice.REPAIR and invoice.repair_ticket_id:
        from repairs.billing import on_repair_invoice_paid

        on_repair_invoice_paid(invoice)
    if invoice.source == Invoice.RENTAL and invoice.rental_id:
        from rentals.billing import on_rent_invoice_paid

        on_rent_invoice_paid(invoice)
