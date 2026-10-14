"""
Meta WhatsApp Cloud API webhook -- delivery status for messages the CRM sent.

Configure in Meta dashboard > WhatsApp > Configuration > Webhook:
    Callback URL:  https://<your backend>/api/whatsapp/meta-webhook/
    Verify token:  the value of WHATSAPP_WEBHOOK_VERIFY_TOKEN
    Subscribe to:  messages
and set WHATSAPP_APP_SECRET (App settings > Basic > App secret) so each
POST's X-Hub-Signature-256 can be checked. Either setting missing means the
endpoint refuses everything -- the safe default.

Only `statuses` are used: they move a CRM Message (and its
WhatsAppDeliveryLog row) from "sent" (Meta accepted it) to delivered / read,
or to failed with Meta's reason -- e.g. 131047 when free text was sent
outside the customer's 24-hour window. This is the ONLY place a message
becomes "delivered". Inbound customer messages are not stored yet.

(The older portal/whatsapp-webhook/ endpoint takes a custom shared-secret
format for other providers and is unchanged.)
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger("crmbook.notify")

# Later states never move back: a "delivered" callback that arrives after
# "read" is ignored. "failed" can follow "sent" (e.g. 131047).
_RANK = {"sending": 0, "unknown": 0, "sent": 1, "delivered": 2, "read": 3}
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

    updated = 0
    for message in Message.objects.filter(provider_message_id=provider_id):
        current = message.delivery_status
        if new != "failed" and _RANK.get(new, 0) <= _RANK.get(current, 0):
            continue
        if new == "failed" and current == "read":
            continue
        message.delivery_status = new
        message.delivery_error = detail
        message.delivery_updated_at = timezone.now()
        message.save(update_fields=["delivery_status", "delivery_error", "delivery_updated_at"])
        updated += 1
    WhatsAppDeliveryLog.objects.filter(provider_message_id=provider_id).update(status=new, detail=detail[:300])
    return updated


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

    updated = 0
    for entry in items(payload, "entry"):
        for change in items(entry, "changes"):
            for status_item in items(change.get("value"), "statuses"):
                updated += _apply_status(status_item)
    # always 200 for a verified request, or Meta keeps retrying it
    return JsonResponse({"updated": updated})
