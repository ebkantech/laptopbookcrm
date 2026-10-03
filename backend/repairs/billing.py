"""What happens on the repair side once a repair invoice is paid."""
from crmbook_backend.notify import send_email, send_whatsapp

from .models import Notification, RepairTicket


def on_repair_invoice_paid(invoice):
    """Payment is what completes a repair: mark the ticket Delivered and
    let the customer know they can collect."""
    ticket = RepairTicket.objects.select_for_update().get(pk=invoice.repair_ticket_id)
    if ticket.unpaid_invoice or ticket.status == RepairTicket.DELIVERED:
        return
    ticket.status = RepairTicket.DELIVERED
    ticket.save(update_fields=["status"])
    text = f"Thank you! Payment received for invoice {invoice.code}. Your {ticket.brand} {ticket.model_name} ({ticket.code}) is ready to collect from {ticket.stock_point.name}."
    Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
    Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
    send_whatsapp(ticket.party.phone, text)
    send_email(ticket.party.email, f"Payment received -- {invoice.code}", text)
