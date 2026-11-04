"""
Meta WhatsApp Cloud API webhook -- delivery status for messages the CRM sent.

Configure in Meta dashboard > WhatsApp > Configuration > Webhook:
    Callback URL:  https://<your backend>/api/whatsapp/meta-webhook/
    Verify token:  the value of WHATSAPP_WEBHOOK_VERIFY_TOKEN
    Subscribe to:  messages
and set WHATSAPP_APP_SECRET (App settings > Basic > App secret) so each
POST's X-Hub-Signature-256 can be checked. Either setting missing means the
endpoint refuses everything -- the safe default.

`statuses` move a CRM Message (and its WhatsAppDeliveryLog row) from
"sent" (Meta accepted it) to delivered / read, or to failed with Meta's
reason -- e.g. 131047 when free text was sent outside the customer's
24-hour window. This is the ONLY place a message becomes "delivered".

`messages` (customer replies) are stored as inbound chat messages on every
party whose phone is the sender's number, once per Meta message id.

(The older portal/whatsapp-webhook/ endpoint takes a custom shared-secret
format for other providers and is unchanged.)
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger("crmbook.notify")

# Later states never move back: a "delivered" callback that arrives after
# "read" is ignored. "failed" can follow "sent" (e.g. 131047).
_RANK = {"sending": 0, "unknown": 0, "failed": 0, "sent": 1, "delivered": 2, "read": 3}
_META_STATUSES = {"sent", "delivered", "read", "failed"}


def _signature_ok(raw_body, header):
    secret = getattr(settings, "WHATSAPP_APP_SECRET", None)
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def _apply_status(item):
    from parties.models import Message

    from .models import WhatsAppDeliveryLog

    provider_id = item.get("id")
    new = item.get("status")
    if not provider_id or new not in _META_STATUSES:
        return 0
    detail = ""
    if new == "failed":
        errors = item.get("errors") or []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        detail = " ".join(str(part) for part in (first.get("code") or "", first.get("title") or first.get("message") or "") if part)
        detail = (f"WhatsApp reported the message failed: {detail}" if detail else "WhatsApp reported the message failed")[:300]

    at = _provider_time(item.get("timestamp"))
    updated = 0
    # Matched by Meta's own message id (wamid) only -- never by number or text.
    for message in Message.objects.filter(provider_message_id=provider_id).select_related("party"):
        if not _moves_forward(message.delivery_status, new):
            continue
        _check_recipient(item.get("recipient_id"), message.party, provider_id)
        message.delivery_status = new
        message.delivery_error = detail
        message.delivery_updated_at = at
        message.save(update_fields=["delivery_status", "delivery_error", "delivery_updated_at"])
        updated += 1
    # the log follows the same rule, so a repeated or late event never moves it back
    for log in WhatsAppDeliveryLog.objects.filter(provider_message_id=provider_id):
        if _moves_forward(log.status, new):
            log.status, log.detail = new, detail[:300]
            log.save(update_fields=["status", "detail", "updated_at"])
    return updated


_MEDIA_LABELS = {"image": "Image", "video": "Video", "audio": "Voice message", "document": "Document",
                 "sticker": "Sticker", "location": "Location", "contacts": "Contact card"}


def _inbound_body(item):
    kind = item.get("type")
    part = item.get(kind) if isinstance(item.get(kind), dict) else {}
    if kind == "text":
        return str(part.get("body") or "")
    if kind == "button":
        return str(part.get("text") or "")
    if kind == "interactive":
        reply = part.get("button_reply") or part.get("list_reply") or {}
        return str(reply.get("title") or "") if isinstance(reply, dict) else ""
    if kind == "reaction":
        return f"Reacted {part.get('emoji')}" if part.get("emoji") else "Removed a reaction"
    if kind in _MEDIA_LABELS:
        caption = part.get("caption") or part.get("filename") or part.get("name") or ""
        return f"[{_MEDIA_LABELS[kind]}] {caption}".strip()
    return "[Unsupported WhatsApp message]"


def _store_inbound(item):
    from crmbook_backend.notify import normalize_whatsapp_number
    from parties.models import Message, Party

    provider_id, sender = item.get("id"), normalize_whatsapp_number(str(item.get("from") or ""))
    if not provider_id or not sender:
        return 0
    # Meta retries until it gets a 200, so the same reply can arrive more than once
    if Message.objects.filter(provider_message_id=provider_id, direction=Message.IN).exists():
        return 0
    parties = [party for party in Party.objects.filter(phone__contains=sender[-4:])
               if normalize_whatsapp_number(party.phone) == sender]
    if not parties:
        logger.warning("[WhatsApp webhook] reply %s is from a number no party has -- not stored", provider_id)
        return 0
    body, at = _inbound_body(item) or "[Empty WhatsApp message]", _provider_time(item.get("timestamp"))
    for party in parties:
        message = Message.objects.create(party=party, channel=Message.WHATSAPP, direction=Message.IN,
                                         body=body, provider_message_id=provider_id)
        Message.objects.filter(pk=message.pk).update(at=at)  # `at` is auto_now_add
    return len(parties)


def _moves_forward(current, new):
    """Duplicates and out-of-order callbacks are no-ops; failed can follow anything but read."""
    if new == "failed":
        return current not in ("failed", "read")
    return _RANK.get(new, 0) > _RANK.get(current, 0)


def _provider_time(value):
    """Meta's own event time (unix seconds) -- the receipt time if it's missing or malformed."""
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return timezone.now()


def _check_recipient(recipient_id, party, provider_id):
    # The wamid already identifies the message; a recipient that isn't the
    # party's current number means the number changed after sending.
    from crmbook_backend.notify import normalize_whatsapp_number

    if recipient_id and normalize_whatsapp_number(str(recipient_id)) != normalize_whatsapp_number(party.phone):
        logger.warning("[WhatsApp webhook] status for %s was for a number other than party %s's current one",
                       provider_id, party.pk)


@csrf_exempt
def meta_whatsapp_webhook(request):
    if request.method == "GET":
        verify_token = getattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", None)
        if (verify_token and request.GET.get("hub.mode") == "subscribe"
                and hmac.compare_digest(request.GET.get("hub.verify_token", ""), verify_token)):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponseForbidden("verification failed")
    if request.method != "POST":
        return HttpResponse(status=405)

    raw = request.body
    if not _signature_ok(raw, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("[WhatsApp webhook] rejected a request with a missing or invalid signature")
        return HttpResponseForbidden("invalid signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "invalid JSON"}, status=400)

    def items(container, key):
        found = container.get(key) if isinstance(container, dict) else None
        return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []

    updated = received = 0
    for entry in items(payload, "entry"):
        for change in items(entry, "changes"):
            for status_item in items(change.get("value"), "statuses"):
                updated += _apply_status(status_item)
            for message_item in items(change.get("value"), "messages"):
                received += _store_inbound(message_item)
    # always 200 for a verified request, or Meta keeps retrying it
    return JsonResponse({"updated": updated, "received": received})
