"""
Customer questions waiting for an answer, on every channel stored on a party's
thread (WhatsApp replies from the Meta webhook, email, customer portal chat).
A draft is written on request, as the staff member reviewing it, so it only
ever uses records that person may see in their own store.
"""
import json

from django.conf import settings
from django.db.models import Exists, OuterRef

from accounts.store_scope import StoreScope
from parties.models import Message
from rentals.models import Rental
from rentals.scope import rental_queryset_for
from repairs.models import RepairTicket

from . import dispatch, llm, prompts, redact
from .models import ReplyDraft

CHANNELS = (Message.WHATSAPP, Message.EMAIL, Message.PORTAL)


def waiting(limit=50):
    later_out = Message.objects.filter(party_id=OuterRef("party_id"), direction=Message.OUT, at__gt=OuterRef("at"), deleted_at__isnull=True)
    later_in = Message.objects.filter(party_id=OuterRef("party_id"), direction=Message.IN, at__gt=OuterRef("at"), deleted_at__isnull=True)
    closed = ReplyDraft.objects.filter(message_id=OuterRef("pk"), status__in=(ReplyDraft.DISMISSED, ReplyDraft.SENT))
    return (Message.objects.filter(direction=Message.IN, channel__in=CHANNELS, deleted_at__isnull=True)
            .annotate(_out=Exists(later_out), _in=Exists(later_in), _closed=Exists(closed))
            .filter(_out=False, _in=False, _closed=False).select_related("party").order_by("-at")[:limit])


def _can(user, code):
    return user.is_superuser or user.has_perm_code(code)


def facts(request, party):
    """(facts, sources) from what this staff member can reach."""
    collected, sources = {}, []
    result = dispatch.call(request, "GET", f"/parties/{party.pk}/")
    if result.ok:
        data = redact.clean(result.data)
        data["messages"] = [{"direction": m.get("direction"), "body": m.get("body"), "at": m.get("at")}
                            for m in (data.get("messages") or [])[-8:]]
        collected["customer"] = data
        sources += [{"type": "invoice", "label": i.get("code")} for i in (data.get("invoices") or []) if i.get("code")][:10]
    scope = StoreScope(request.user)
    if _can(request.user, "repairs.view"):
        rows = scope.filter(RepairTicket.objects.filter(party=party), "stock_point").order_by("-id")[:5]
        collected["repairs"] = [{"code": t.code, "device": f"{t.brand} {t.model_name}", "status": t.status} for t in rows]
        sources += [{"type": "repair", "label": t["code"]} for t in collected["repairs"]]
    if _can(request.user, "rentals.view"):
        rows = rental_queryset_for(scope, Rental.objects.filter(party=party)).order_by("-id")[:5]
        collected["rentals"] = [{"code": r.agreement_code, "status": r.status, "start": r.start, "months": r.tenure_months}
                                for r in rows]
        sources += [{"type": "rental", "label": r["code"]} for r in collected["rentals"] if r["code"]]
    return collected, sources


def draft(request, message):
    collected, sources = facts(request, message.party)
    content = (f"<customer_message channel=\"{message.channel}\">\n{message.body}\n</customer_message>\n"
               f"<crm_facts>\n{json.dumps(collected, default=str)[:redact.MAX_CHARS]}\n</crm_facts>\n"
               f"Business name: {settings.BUSINESS_NAME}")
    result = llm.complete(prompts.DRAFT_SYSTEM, [{"role": "user", "content": content}], max_tokens=400)
    body = llm.text_of(result)
    if not body:
        raise llm.LLMError("The AI service returned an empty draft. Try again.")
    ReplyDraft.objects.filter(message=message, status=ReplyDraft.PENDING).delete()
    return ReplyDraft.objects.create(party=message.party, message=message, body=body, sources=sources, created_by=request.user)
