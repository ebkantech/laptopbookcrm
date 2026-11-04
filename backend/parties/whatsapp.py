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
import re
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


def apply_send_result(message, result):
    """Record a send made elsewhere (the portal invite's WhatsApp) on its "sending" chat row."""
    return _apply_result(message, result)


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


# What the CRM's own WhatsApp history proves about a party's number. Meta's
# Cloud API can't look a number up (notify.check_whatsapp_number), so the
# only real proof is a message the CRM sent that Meta's webhook confirmed
# delivered or read (portal/meta_webhook.py is the only place that happens).
VERIFIED, NOT_VERIFIED, PENDING, UNABLE = "verified", "not_verified", "pending", "unable"
# 131026 "message undeliverable" is the closest Meta comes to "not on WhatsApp",
# but Meta lists other causes for it too (terms not accepted, an outdated app),
# so it is reported as unable-to-verify, never as a confirmed "no". The webhook
# stores it as "WhatsApp reported the message failed: 131026 ...", a failed
# send as notify's hint text "...may not be on WhatsApp".
_UNDELIVERABLE = re.compile(r"\b131026\b|may not be on WhatsApp")


def last_phone_change(party):
    """When staff last edited this party's phone number (Activity Logs keep
    the time, with the number itself masked), or None if never recorded."""
    from accounts.models import ActivityLog

    return (ActivityLog.objects
            .filter(record_type="parties.party", record_id=str(party.pk), changes__has_key="phone")
            .order_by("-at").values_list("at", flat=True).first())


def delivery_evidence(party):
    """
    (status, reason) from the party's outbound CRM WhatsApp messages, or
    (None, None) when they prove nothing. Messages carry no recipient
    number -- each went to the party's own Party.phone at the time -- so
    only messages written after the last phone change count, and a
    message only ever counts for its own party.

    verified   a message was delivered or read, or the customer replied on WhatsApp
    pending    the latest message was accepted by Meta, delivery not yet confirmed
    unable     the latest send failed (undeliverable, auth, rate limit, network...)

    Meta never confirms "this number isn't on WhatsApp", so this never
    returns not_verified -- that only comes from the console provider's check.
    """
    messages = party.messages.filter(channel=Message.WHATSAPP, direction=Message.OUT).exclude(
        delivery_status__in=["", Message.DELIVERY_SIMULATED])
    since = last_phone_change(party)
    if since:
        messages = messages.filter(at__gt=since)
    if messages.filter(delivery_status__in=[Message.DELIVERY_DELIVERED, Message.DELIVERY_READ]).exists():
        return VERIFIED, "a WhatsApp message from the CRM was delivered to this number"
    # a reply received through Meta's webhook (CRM-typed history has no Meta id)
    replies = party.messages.filter(channel=Message.WHATSAPP, direction=Message.IN).exclude(provider_message_id="")
    if since:
        replies = replies.filter(at__gt=since)
    if replies.exists():
        return VERIFIED, "the customer has sent a WhatsApp message from this number"
    latest = messages.order_by("-at", "-id").first()
    if latest is None:
        return None, None
    if latest.delivery_status == Message.DELIVERY_FAILED and _UNDELIVERABLE.search(latest.delivery_error or ""):
        return UNABLE, ("WhatsApp couldn't deliver the latest message (Meta error 131026): the number may not be on "
                        "WhatsApp, or the customer hasn't accepted WhatsApp's terms or updated the app")
    if latest.delivery_status in (Message.DELIVERY_SENT, Message.DELIVERY_SENDING):
        return PENDING, "the latest WhatsApp message was accepted by Meta, but its delivery isn't confirmed yet"
    return UNABLE, latest.delivery_error or "the latest WhatsApp message couldn't be sent"
