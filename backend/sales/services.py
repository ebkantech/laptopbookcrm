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
    if invoice.status in Invoice.SETTLED:
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


class RefundError(Exception):
    pass


@transaction.atomic
def refund_invoice(invoice, user, *, method, reference="", reason="", refunded_on=None, items=None, amount=None, restock=True):
    """
    Pay money back on a paid invoice.
      Sale    -> items: [{"item": InvoiceItem id, "qty": n}] being returned;
                 the refund is their value, and with restock=True the
                 units go back on the shelf they were sold from.
      Others  -> amount: rupees to pay back (repair goodwill, rent, or a
                 repair advance returned).
    Refunds can add up to the invoice total, never more; once the whole
    total is refunded the invoice becomes Refunded. The refund is posted
    out of the cash or bank book.
    """
    from accounting.posting import post_refund
    from catalog.models import Stock

    from .models import PAYMENT_METHODS, Invoice, Refund, RefundItem

    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.PAID:
        if invoice.status == Invoice.REFUNDED:
            raise RefundError("This invoice has already been refunded in full.")
        raise RefundError("Only a paid invoice can be refunded -- cancel an unpaid one instead.")
    if invoice.total <= 0:
        raise RefundError("Nothing was collected on this invoice, so there's nothing to refund.")
    reason = (reason or "").strip()
    reference = (reference or "").strip()
    if not reason:
        raise RefundError("Give a reason for the refund.")
    if method not in PAYMENT_METHODS:
        raise RefundError(f"Refund method must be one of: {', '.join(PAYMENT_METHODS)}.")
    if method != "Cash" and not reference:
        raise RefundError("Enter the refund reference (UPI/UTR, cheque or transaction number).")
    if len(reference) > 80:
        raise RefundError("The reference must be 80 characters or fewer.")
    refunded_on = refunded_on or timezone.localdate()
    if refunded_on > timezone.localdate():
        raise RefundError("The refund date can't be in the future.")
    if refunded_on < (invoice.paid_on or invoice.date):
        raise RefundError("The refund date can't be before the invoice was paid.")

    returned = []
    if invoice.source == Invoice.SALE:
        lines = {item.id: item for item in invoice.items.all()}
        wanted = {}
        for row in items or []:
            try:
                item_id, qty = int(row["item"]), int(row["qty"])
            except (KeyError, TypeError, ValueError):
                raise RefundError("Each returned item needs an item and a quantity.")
            if qty <= 0:
                continue
            if item_id not in lines:
                raise RefundError("That item isn't on this invoice.")
            wanted[item_id] = wanted.get(item_id, 0) + qty
        if not wanted:
            raise RefundError("Choose the items being returned and how many.")
        for item_id, qty in wanted.items():
            item = lines[item_id]
            already = sum(r.qty for r in item.refund_items.all())
            if qty > item.qty - already:
                left = item.qty - already
                raise RefundError(f"{item.label}: only {left} left to return on this invoice." if left else f"{item.label} has already been returned.")
            returned.append((item, qty))
        amount = sum(item.price * qty for item, qty in returned)
    else:
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise RefundError("Enter the amount to refund.")
    if amount <= 0:
        raise RefundError("The refund amount must be more than zero.")
    left = invoice.total - invoice.refunded_total
    if amount > left:
        raise RefundError(f"Only ₹{left} is left to refund on this invoice.")

    restock = bool(restock and returned)
    refund = Refund.objects.create(
        invoice=invoice, amount=amount, method=method, reference=reference, reason=reason[:200],
        refunded_on=refunded_on, restocked=restock, by=user,
    )
    for item, qty in returned:
        RefundItem.objects.create(refund=refund, invoice_item=item, qty=qty)
        if restock and item.variant_id:
            updated = Stock.objects.filter(variant_id=item.variant_id, stock_point_id=invoice.stock_point_id).update(quantity=F("quantity") + qty)
            if not updated:
                Stock.objects.create(variant_id=item.variant_id, stock_point_id=invoice.stock_point_id, quantity=qty)
    if amount == left:
        invoice.status = Invoice.REFUNDED
        invoice.save(update_fields=["status"])
    post_refund(refund)

    if invoice.is_advance and invoice.repair_ticket_id:
        from repairs.billing import on_repair_advance_refunded

        on_repair_advance_refunded(invoice, refund)
    return refund
