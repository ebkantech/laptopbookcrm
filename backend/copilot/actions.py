"""Confirming a prepared change: one person, one run, under the same role and store."""
from datetime import timedelta

from django.utils import timezone

from . import catalog, dispatch
from .models import ProposedAction

TTL = timedelta(minutes=30)


class ActionRefused(Exception):
    pass


def _verify(request, proposal):
    """Read the record back so the card reports what the CRM now shows, not what was intended."""
    spec = catalog.ACTIONS.get(proposal.action_key)
    if not spec or not spec.describe or not spec.describe[2]:
        return ""
    template, describe, (field, expected) = spec.describe
    ids = dict(zip(spec.ids, [part for part in proposal.path.split("/") if part.isdigit()]))
    result = dispatch.call(request, "GET", template.format(**ids))
    if not result.ok or not isinstance(result.data, dict):
        return "Couldn't read the record back. Check it in the CRM."
    actual = result.data.get(field)
    if actual == expected:
        return f"Verified: {describe(result.data)}"[:240]
    return f"Check this: {field} is now {actual}, expected {expected}."[:240]


def _delivery(result):
    """For a message: what actually happened to it, since saving it isn't sending it."""
    data = result.data if isinstance(result.data, dict) else {}
    status = data.get("delivery_status")
    if status == "simulated":
        return "Not sent: WhatsApp isn't connected yet, so this was only saved in the CRM."
    if status in ("failed", "unknown"):
        return f"Not confirmed as sent: {data.get('delivery_error') or 'sending failed'}"[:240]
    if status in ("sent", "delivered", "read"):
        return "Sent. Delivery updates appear on the customer's chat."
    return ""


def confirm(request, proposal):
    if proposal.user_id != request.user.id:
        raise ActionRefused("This isn't your action.")
    if (request.META.get("HTTP_X_ACTIVE_ROLE", "")[:20] != proposal.active_role
            or request.META.get("HTTP_X_ACTIVE_STORE", "")[:20] != proposal.active_store):
        raise ActionRefused("This was prepared under a different role or store. Switch back, or ask Copilot again.")
    if timezone.now() - proposal.created_at > TTL:
        ProposedAction.objects.filter(pk=proposal.pk, status=ProposedAction.PROPOSED).update(status=ProposedAction.EXPIRED)
        raise ActionRefused("This has expired. Ask Copilot to prepare it again so it uses current data.")
    claimed = ProposedAction.objects.filter(pk=proposal.pk, status=ProposedAction.PROPOSED).update(
        status=ProposedAction.EXECUTING, decided_at=timezone.now())
    if not claimed:
        raise ActionRefused("This has already been handled.")
    try:
        result = dispatch.call(request, proposal.method, proposal.path, body=proposal.body)
    except Exception:
        ProposedAction.objects.filter(pk=proposal.pk).update(status=ProposedAction.FAILED, result="The CRM hit an error. Check the record before trying again.")
        proposal.refresh_from_db()
        return proposal
    proposal.status = ProposedAction.DONE if result.ok else ProposedAction.FAILED
    proposal.result = "Done." if result.ok else result.error[:500]
    proposal.verification = (_delivery(result) or _verify(request, proposal)) if result.ok else ""
    proposal.save(update_fields=["status", "result", "verification"])
    return proposal


def reject(request, proposal):
    if proposal.user_id != request.user.id:
        raise ActionRefused("This isn't your action.")
    claimed = ProposedAction.objects.filter(pk=proposal.pk, status=ProposedAction.PROPOSED).update(
        status=ProposedAction.REJECTED, decided_at=timezone.now())
    if not claimed:
        raise ActionRefused("This has already been handled.")
    proposal.refresh_from_db()
    return proposal
