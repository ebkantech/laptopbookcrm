"""
Sending a CRM thread message to the customer's WhatsApp.

The Parties chat and the Rentals "Chat on WhatsApp" modal are the same
composer (components/PartyThread.jsx) posting to /parties/<id>/messages/;
both land here. The message row is saved first, then sent through the
shared notify.send_whatsapp() -- never inside an open database
transaction -- and the row records what actually happened. The number is
always the party's own Party.phone, read on the server; the request can't
choose a recipient.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from crmbook_backend.notify import send_whatsapp

from .models import Message

# Meta's limit for a WhatsApp text message body.
WHATSAPP_TEXT_LIMIT = 4096
# Results where Meta may or may not have accepted the message: never
# resent automatically, only after staff confirm.
UNCERTAIN_ERRORS = {"timeout", "malformed_response", "unexpected"}
# A row stuck in "sending" this long (worker died mid-send) counts as
# uncertain rather than in flight.
STALE_SENDING = timedelta(minutes=2)


class RetryRefused(Exception):
    def __init__(self, detail, code):
        super().__init__(detail)
        self.detail = detail
        self.code = code


def _apply_result(message, result):
    status = result.get("status")
    now = timezone.now()
    fields = {"delivery_updated_at": now, "provider_message_id": "", "delivery_error": ""}
    if status == "sent":
        fields.update(delivery_status=Message.DELIVERY_SENT, provider_message_id=result.get("provider_id") or "",
                      # an accepted WhatsApp can't be edited or recalled
                      is_editable=False)
    elif status == "simulated":
        fields.update(delivery_status=Message.DELIVERY_SIMULATED,
                      delivery_error="WhatsApp API is in console (simulation) mode -- nothing was sent")
    elif result.get("error_code") in UNCERTAIN_ERRORS:
        fields.update(delivery_status=Message.DELIVERY_UNKNOWN, delivery_error=(result.get("reason") or "")[:300])
    else:
        fields.update(delivery_status=Message.DELIVERY_FAILED,
                      delivery_error=(result.get("reason") or "the message could not be sent")[:300])
    # only touch the row if nothing else (e.g. a webhook) has moved it on
    Message.objects.filter(pk=message.pk, delivery_status=Message.DELIVERY_SENDING).update(**fields)
    message.refresh_from_db()
    if message.provider_message_id:
        from portal.models import WhatsAppDeliveryLog

        WhatsAppDeliveryLog.objects.get_or_create(
            party_id=message.party_id, provider_message_id=message.provider_message_id,
            defaults={"status": WhatsAppDeliveryLog.SENT},
        )
    return message


def deliver(message):
    """Send a row already claimed as "sending". Must not run inside an atomic block."""
    party = message.party
    result = send_whatsapp(party.phone, message.body)
    return _apply_result(message, result)


def claim_for_retry(message, confirm_uncertain=False):
    """Atomically move a failed/uncertain row back to "sending" so two
    clicks (or two staff) can never send it twice. Returns the row."""
    if message.channel != Message.WHATSAPP or message.direction != Message.OUT:
        raise RetryRefused("Only outgoing WhatsApp messages can be resent.", "not_whatsapp")
    if message.deleted_at:
        raise RetryRefused("This message was deleted.", "deleted")
    stale = timezone.now() - STALE_SENDING
    retryable = Q(delivery_status__in=[Message.DELIVERY_FAILED, Message.DELIVERY_SIMULATED])
    uncertain = Q(delivery_status=Message.DELIVERY_UNKNOWN) | Q(delivery_status=Message.DELIVERY_SENDING, delivery_updated_at__lt=stale)
    if confirm_uncertain:
        retryable |= uncertain
    claimed = Message.objects.filter(retryable, pk=message.pk, deleted_at__isnull=True).update(
        delivery_status=Message.DELIVERY_SENDING, delivery_updated_at=timezone.now(), delivery_error="",
    )
    if claimed:
        message.refresh_from_db()
        return message
    message.refresh_from_db()
    if message.delivery_status in (Message.DELIVERY_SENT, Message.DELIVERY_DELIVERED, Message.DELIVERY_READ):
        raise RetryRefused("This message was already sent to WhatsApp.", "already_sent")
    if message.delivery_status == Message.DELIVERY_UNKNOWN or (
            message.delivery_status == Message.DELIVERY_SENDING and message.delivery_updated_at and message.delivery_updated_at < stale):
        raise RetryRefused("It's unclear whether this message reached WhatsApp -- it may already have been sent. "
                           "Confirm to send it again.", "confirm_required")
    if message.delivery_status == Message.DELIVERY_SENDING:
        raise RetryRefused("This message is already being sent.", "in_progress")
    raise RetryRefused("This message wasn't sent through WhatsApp, so it can't be resent.", "not_sendable")
