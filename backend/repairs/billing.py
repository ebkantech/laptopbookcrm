"""What happens on the repair side when repair invoices are raised, paid or refunded."""
from datetime import timedelta

from django.utils import timezone

from crmbook_backend.notify import send_email, send_whatsapp

from .models import Notification, RepairTicket

ADVANCE_SHARE = 0.25
PORTAL_AFTER_PAYMENT = timedelta(hours=24)


def advance_amount(services):
    """The 25% advance asked for when a job is booked."""
    return round(sum(s.charge for s in services) * ADVANCE_SHARE)


def raise_advance_invoice(ticket, amount):
    """
    Book the advance as a real invoice in Sales & Invoices, due today.
    ticket.advance_paid is only set once it's paid, so the final bill
    deducts money actually received -- never an advance that was only
    asked for.
    """
    from sales.models import Invoice
    from sales.services import create_invoice

    if amount <= 0:
        return None
    today = timezone.localdate()
    return create_invoice(
        source=Invoice.REPAIR, repair_ticket=ticket, is_advance=True, party=ticket.party,
        stock_point=ticket.stock_point, date=today, due_date=today, status=Invoice.LINK_SENT,
        lines=[{"description": f"Advance for repair {ticket.code} ({ticket.brand} {ticket.model_name})", "qty": 1, "price": amount}],
    )


def _tell(job, key, /, **values):
    from branding import texts

    text = texts.message(key, **values)
    subject, email_text = texts.email(key, **values)
    Notification.objects.create(ticket=job, channel=Notification.WHATSAPP, text=text)
    Notification.objects.create(ticket=job, channel=Notification.EMAIL, text=email_text)
    send_whatsapp(job.party.phone, text)
    send_email(job.party.email, subject, email_text)


def on_repair_advance_refunded(invoice, refund):
    """Money handed back from the advance no longer counts against the bill."""
    ticket = RepairTicket.objects.select_for_update().get(pk=invoice.repair_ticket_id)
    ticket.advance_paid = max(0, ticket.advance_paid - refund.amount)
    ticket.save(update_fields=["advance_paid"])


def on_repair_invoice_paid(invoice):
    """Payment is what completes a repair: mark the ticket Delivered and
    let the customer know they can collect."""
    ticket = RepairTicket.objects.select_for_update().get(pk=invoice.repair_ticket_id)
    if invoice.is_advance:
        # the advance: record it against the job, which carries on as before
        ticket.advance_paid += invoice.total
        ticket.save(update_fields=["advance_paid"])
        _tell(ticket, "repair_advance_received", amount=invoice.total, ticket=ticket.code, invoice=invoice.code)
        return
    if ticket.unpaid_invoice or ticket.status == RepairTicket.DELIVERED:
        return
    ticket.status = RepairTicket.DELIVERED
    ticket.portal_until = timezone.now() + PORTAL_AFTER_PAYMENT if invoice.total > 0 else None
    ticket.save(update_fields=["status", "portal_until"])
    _tell(ticket, "repair_paid", invoice=invoice.code, device=f"{ticket.brand} {ticket.model_name}", ticket=ticket.code,
          store=ticket.stock_point.name)


def reconcile_delivery(ticket):
    """Self-heal: a ticket still at Ready for pickup whose bill has been paid
    is delivered. Normally payment does this itself (on_repair_invoice_paid);
    this catches a payment whose follow-up step didn't complete."""
    from django.db import transaction

    if ticket.status != RepairTicket.READY or ticket.active_reopen or ticket.unpaid_invoice:
        return False
    paid = ticket.invoices.filter(is_advance=False, status__in=("Paid", "Refunded")).order_by("-id").first()
    if not paid:
        return False
    with transaction.atomic():
        on_repair_invoice_paid(paid)
    ticket.refresh_from_db(fields=["status"])
    return ticket.status == RepairTicket.DELIVERED
