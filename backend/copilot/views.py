from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from parties.models import Message

from . import actions as action_flow
from . import agent, catalog, dispatch, inbox, llm
from .models import Conversation, ProposedAction, ReplyDraft
from .serializers import (
    ChatMessageSerializer, ConversationSerializer, InboxMessageSerializer, ProposedActionSerializer, ReplyDraftSerializer,
)

MAX_MESSAGE = 4000


class CopilotThrottle(UserRateThrottle):
    scope = "copilot"


class CopilotView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "copilot.use"


class InboxView(CopilotView):
    required_perm = "parties.manage"


def _service_unavailable(error):
    return Response({"detail": str(error), "code": "copilot_unavailable"}, status=503)


def _record_id(value):
    """A record id from a request body; anything else simply finds nothing."""
    return int(value) if str(value).isdigit() else 0


def _needs_token(request):
    if not request.META.get("HTTP_AUTHORIZATION"):
        return Response({"detail": "Sign in again to use Copilot."}, status=401)
    return None


class StatusView(CopilotView):
    def get(self, request):
        role = getattr(request.user, "role", None)
        slug = "owner" if request.user.is_superuser else (role.slug if role else "")
        can_inbox = request.user.is_superuser or request.user.has_perm_code("parties.manage")
        return Response({
            "enabled": llm.is_configured(),
            "suggestions": catalog.SUGGESTIONS.get(slug, catalog.DEFAULT_SUGGESTIONS),
            "actions": [a.label for a in catalog.available(request.user)],
            "can_use_inbox": can_inbox,
            "inbox_count": len(inbox.waiting()) if can_inbox else 0,
        })


class ChatView(CopilotView):
    throttle_classes = [CopilotThrottle]

    def post(self, request):
        refused = _needs_token(request)
        if refused:
            return refused
        text = str(request.data.get("message") or "").strip()
        if not text:
            return Response({"detail": "Type a message first."}, status=400)
        if len(text) > MAX_MESSAGE:
            return Response({"detail": f"Keep messages under {MAX_MESSAGE:,} characters."}, status=400)
        conversation_id = request.data.get("conversation")
        if conversation_id:
            conversation = get_object_or_404(Conversation, pk=_record_id(conversation_id), user=request.user)
        else:
            conversation = Conversation.objects.create(user=request.user, title=text[:120])
        before = set(conversation.actions.values_list("id", flat=True))
        try:
            reply = agent.chat(request, conversation, text)
        except llm.LLMError as error:
            return _service_unavailable(error)
        conversation.save(update_fields=["updated_at"])
        created = conversation.actions.exclude(id__in=before)
        return Response({"conversation": conversation.id, "reply": reply,
                         "actions": ProposedActionSerializer(created, many=True).data})


class ConversationsView(CopilotView):
    def get(self, request):
        rows = Conversation.objects.filter(user=request.user)[:30]
        return Response(ConversationSerializer(rows, many=True).data)


class ConversationDetailView(CopilotView):
    def get(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk, user=request.user)
        return Response({
            **ConversationSerializer(conversation).data,
            "messages": ChatMessageSerializer(conversation.messages.all(), many=True).data,
            "actions": ProposedActionSerializer(conversation.actions.all(), many=True).data,
        })


class ActionDecisionView(CopilotView):
    decide = None

    def post(self, request, pk):
        refused = _needs_token(request)
        if refused:
            return refused
        proposal = get_object_or_404(ProposedAction, pk=pk, user=request.user)
        try:
            proposal = type(self).decide(request, proposal)
        except action_flow.ActionRefused as refusal:
            return Response({"detail": str(refusal)}, status=409)
        return Response(ProposedActionSerializer(proposal).data)


class ConfirmActionView(ActionDecisionView):
    decide = staticmethod(action_flow.confirm)


class RejectActionView(ActionDecisionView):
    decide = staticmethod(action_flow.reject)


class InboxListView(InboxView):
    def get(self, request):
        return Response(InboxMessageSerializer(inbox.waiting(), many=True).data)


class DraftCreateView(InboxView):
    throttle_classes = [CopilotThrottle]

    def post(self, request):
        refused = _needs_token(request)
        if refused:
            return refused
        message = get_object_or_404(Message, pk=_record_id(request.data.get("message")), direction=Message.IN, deleted_at__isnull=True)
        try:
            draft = inbox.draft(request, message)
        except llm.LLMError as error:
            return _service_unavailable(error)
        return Response(ReplyDraftSerializer(draft).data, status=201)


class DraftSendView(InboxView):
    def post(self, request, pk):
        refused = _needs_token(request)
        if refused:
            return refused
        draft = get_object_or_404(ReplyDraft.objects.select_related("message"), pk=pk)
        body = str(request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "The reply is empty."}, status=400)
        claimed = ReplyDraft.objects.filter(pk=pk, status=ReplyDraft.PENDING).update(status=ReplyDraft.SENDING)
        if not claimed:
            return Response({"detail": "This reply has already been handled."}, status=409)
        result = dispatch.call(request, "POST", f"/parties/{draft.party_id}/messages/",
                               body={"channel": draft.message.channel, "body": body})
        if not result.ok:
            ReplyDraft.objects.filter(pk=pk).update(status=ReplyDraft.PENDING)
            return Response({"detail": result.error}, status=result.status if result.status < 500 else 502)
        ReplyDraft.objects.filter(pk=pk).update(
            status=ReplyDraft.SENT, sent_by=request.user, sent_message_id=result.data.get("id"),
            edited=body != draft.body, decided_at=timezone.now(), body=body)
        return Response({"id": pk, "status": ReplyDraft.SENT, "delivery_status": result.data.get("delivery_status"),
                         "delivery_error": result.data.get("delivery_error")})


class DismissView(InboxView):
    """Close a customer message that needs no reply."""

    def post(self, request):
        message = get_object_or_404(Message, pk=_record_id(request.data.get("message")), direction=Message.IN)
        with transaction.atomic():
            ReplyDraft.objects.filter(message=message, status=ReplyDraft.PENDING).update(
                status=ReplyDraft.DISMISSED, decided_at=timezone.now())
            if not ReplyDraft.objects.filter(message=message, status=ReplyDraft.DISMISSED).exists():
                ReplyDraft.objects.create(party=message.party, message=message, body="", status=ReplyDraft.DISMISSED,
                                          created_by=request.user, decided_at=timezone.now())
        return Response(status=204)


class TasksView(CopilotView):
    """Today's queue for this person's role: only what their permissions can open."""
    CHECKS = [
        ("invoices.view", "Overdue invoices", "/invoices/", {"status": "Overdue"}, "Show overdue invoices and who to chase first"),
        ("repairs.view", "My repair jobs", "/tickets/", {"mine": "1"}, "What are my repair jobs and what's next on each?"),
        ("repairs.view", "Ready for pickup", "/tickets/", {"status": "Ready"}, "Which repairs are ready for pickup?"),
        ("rentals.view", "Open rental issues", "/rental-issues/", {"status": "Open"}, "Show open rental issues"),
        ("orders.manage", "WhatsApp orders", "/whatsapp-orders/", {}, "Show WhatsApp orders that need a quote"),
    ]

    def get(self, request):
        refused = _needs_token(request)
        if refused:
            return refused
        tasks = []
        for perm, title, path, query, prompt in self.CHECKS:
            if not (request.user.is_superuser or request.user.has_perm_code(perm)):
                continue
            result = dispatch.call(request, "GET", path, query=query)
            if not result.ok:
                continue
            data = result.data
            count = data.get("count") if isinstance(data, dict) else len(data or [])
            if count:
                tasks.append({"title": title, "count": count, "prompt": prompt})
        return Response(tasks)
