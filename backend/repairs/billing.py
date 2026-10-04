"""What happens on the repair side when repair invoices are raised, paid or refunded."""
from django.utils import timezone

from crmbook_backend.notify import send_email, send_whatsapp

from .models import Notification, RepairTicket

ADVANCE_SHARE = 0.25


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


def _tell(ticket, text, subject):
    Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
    Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
    send_whatsapp(ticket.party.phone, text)
    send_email(ticket.party.email, subject, text)


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
        _tell(ticket, f"Thank you! Advance of Rs {invoice.total} received for {ticket.code} (invoice {invoice.code}). It will be deducted from your final bill.", f"Advance received -- {invoice.code}")
        return
    if ticket.unpaid_invoice or ticket.status == RepairTicket.DELIVERED:
        return
    ticket.status = RepairTicket.DELIVERED
    ticket.save(update_fields=["status"])
    text = f"Thank you! Payment received for invoice {invoice.code}. Your {ticket.brand} {ticket.model_name} ({ticket.code}) is ready to collect from {ticket.stock_point.name}."
    _tell(ticket, text, f"Payment received -- {invoice.code}")
