from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from crmbook_backend.notify import check_whatsapp_number, send_email, send_whatsapp
from portal.models import PortalAccessLog, PortalInvite, WhatsAppDeliveryLog
from portal import otp_vault
from portal.services import (
    create_portal_invite, current_staff_otp, invite_policy_data, invite_whatsapp_body, log_otp_disclosure, otp_history,
    revoke_open_invites, send_invite_whatsapp,
)
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from .models import Message, MessageHidden, MessageRevision, Party
from .serializers import MessageRecordSerializer, MessageSerializer, PartyDetailSerializer, PartySerializer
from . import whatsapp as party_whatsapp


def _mask_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"


def _check_and_record_whatsapp(party):
    """Runs the Task 3 WhatsApp check and writes the result onto the
    party -- shared by create and update (phone-change) paths."""
    result = check_whatsapp_number(party.phone)
    party.whatsapp_verified = result["has_whatsapp"]
    if result["checked"]:
        party.whatsapp_checked_at = timezone.now()
    party.save(update_fields=["whatsapp_verified", "whatsapp_checked_at"])
    return result


def _save_outbound_message(serializer, party):
    """
    Save a staff-written thread message; a WhatsApp one is then sent to the
    party's own number through the shared WhatsApp sender. The row is
    committed first and the send runs outside any transaction, so a slow
    Meta response never holds a lock, and the row always reflects what
    actually happened (sent / failed / outcome unknown / simulated).
    An email one is sent the same way, through the shared SMTP sender.
    """
    if serializer.validated_data["channel"] == Message.WHATSAPP:
        message = serializer.save(party=party, direction=Message.OUT, is_editable=True,
                                  delivery_status=Message.DELIVERY_SENDING, delivery_updated_at=timezone.now())
        return party_whatsapp.deliver(message)
    if serializer.validated_data["channel"] == Message.EMAIL:
        message = serializer.save(party=party, direction=Message.OUT, is_editable=True,
                                  delivery_status=Message.DELIVERY_SENDING, delivery_updated_at=timezone.now())
        return _deliver_email(message)
    return serializer.save(party=party, direction=Message.OUT, is_editable=True)


def _deliver_email(message):
    """
    One SMTP attempt for a saved email message. "sent" only means the mail
    server accepted it -- there's no inbox confirmation for email. A skip
    (no address on file) counts as failed: nothing left the CRM.
    """
    result = send_email(message.party.email, f"Message from {settings.BUSINESS_NAME}", message.body)
    if result.get("status") == "sent":
        message.delivery_status, message.delivery_error = Message.DELIVERY_SENT, ""
    else:
        reason = result.get("reason") or "the mail server didn't accept the email -- check the email settings and server log"
        max_length = Message._meta.get_field("delivery_error").max_length
        message.delivery_status, message.delivery_error = Message.DELIVERY_FAILED, reason[:max_length]
    message.delivery_updated_at = timezone.now()
    message.save(update_fields=["delivery_status", "delivery_error", "delivery_updated_at"])
    return message


def _can_read_portal_otp(user):
    return bool(user and (user.is_superuser or user.has_perm_code("portal.manage")))


def _staff_otp_fields(request, party):
    """The current code for staff holding portal.manage -- nothing for anyone else."""
    if not _can_read_portal_otp(request.user):
        return {}
    row, code = current_staff_otp(party)
    if not code:
        return {}
    log_otp_disclosure(request, party, 1)
    return {"otp": code, "otp_message_id": row["message_id"]}


def _issue_portal_invite(party, request):
    """
    Shared by portal-invite and portal-reset-link: the token-based portal
    has no password to reset, so "resend a link" and "reset access" are the
    same action underneath -- a fresh link + OTP (replacing any older link),
    exactly like PortalInviteViewSet.create in the portal app. The link
    lasts until the rental tenure ends (Rental) or 24 hours (Dealer/Retail);
    each emailed code lasts 30 minutes -- see portal.access.

    Task 3's fallback path: a party flagged whatsapp_verified=False (a
    known-bad number, not just "not checked yet") skips the WhatsApp send
    attempt entirely -- the email+OTP path below is not optional and
    always runs, so the customer can still get in even when WhatsApp
    delivery isn't possible.
    """
    invite, delivery_status = create_portal_invite(party, request.user)
    link = f"{settings.PUBLIC_FRONTEND_URL}/portal/{invite.token}"

    # The link is always kept on the CRM WhatsApp thread so staff can copy
    # it from there, even when the WhatsApp send itself is skipped.
    wa_body = invite_whatsapp_body(invite, link)
    Message.objects.create(party=party, channel=Message.WHATSAPP, direction=Message.OUT, body=wa_body)
    whatsapp_delivery = send_invite_whatsapp(party, invite, link)
    return invite, link, delivery_status, whatsapp_delivery


class PartyViewSet(viewsets.ModelViewSet):
    queryset = Party.objects.prefetch_related("invoices__items", "invoices__stock_point", "messages").all()
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "parties.view", "retrieve": "parties.view",
        "create": "parties.manage", "update": "parties.edit",
        "partial_update": "parties.edit", "destroy": "parties.manage",
        "portal_account": "parties.view",
        "portal_invite": "parties.manage", "portal_reset_link": "parties.manage",
        "send_message": "parties.manage",
        "recheck_whatsapp": "parties.manage",
        "revoke_portal_access": "parties.manage",
        "portal_otp": "portal.manage",
        "portal_otp_history": "portal.manage",
    }

    def get_serializer_class(self):
        return PartyDetailSerializer if self.action == "retrieve" else PartySerializer

    def perform_create(self, serializer):
        party = serializer.save()
        _check_and_record_whatsapp(party)

    def perform_update(self, serializer):
        old_phone = serializer.instance.phone
        party = serializer.save()
        if party.phone != old_phone:
            _check_and_record_whatsapp(party)

    def destroy(self, request, *args, **kwargs):
        """Delete only an unused party; never cascade-delete its history."""
        with transaction.atomic():
            party = self.get_object()
            # Party has several CASCADE relations (messages, portal events,
            # warranties, etc.) alongside PROTECT relations (invoices,
            # repairs and rentals). Block deletion for every relation so
            # historical/customer records are retained consistently.
            related_records = []
            for relation in party._meta.related_objects:
                related_model = relation.related_model
                lookup = {relation.field.name: party}
                if related_model._base_manager.filter(**lookup).exists():
                    related_records.append(related_model._meta.verbose_name_plural)
            if related_records:
                return Response(
                    {"detail": "This customer has linked records and cannot be deleted. "
                     "Keep the customer record to preserve its history.",
                     "related_records": related_records},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                self.perform_destroy(party)
            except ProtectedError:
                return Response(
                    {"detail": "This customer has linked records and cannot be deleted. "
                     "Keep the customer record to preserve its history."},
                    status=status.HTTP_409_CONFLICT,
                )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    @action(detail=True, methods=["get"], url_path="portal-account")
    def portal_account(self, request, pk=None):
        party = self.get_object()
        latest_log = PortalAccessLog.objects.filter(party=party).order_by("-created_at").first()
        latest_invite = PortalInvite.objects.filter(party=party).order_by("-created_at").first()
        if not latest_invite:
            return Response({"enabled": False, "status": "not_created"})
        revoked = bool(party.portal_access_revoked_at and party.portal_access_revoked_at >= latest_invite.created_at)
        status = "revoked" if revoked else ("active" if latest_log else ("pending" if latest_invite.is_valid else "expired"))
        return Response({
            "enabled": True,
            "status": status,
            "phone": _mask_phone(party.phone),
            "activated_at": latest_log.created_at if latest_log else None,
            "last_link": {
                "created_at": latest_invite.created_at,
                "expires_at": latest_invite.expires_at,
                "usable": latest_invite.is_valid,
            },
        })

    @action(detail=True, methods=["post"], url_path="portal-invite")
    def portal_invite(self, request, pk=None):
        party = self.get_object()
        try:
            invite, link, delivery_status, whatsapp_delivery = _issue_portal_invite(party, request)
        except ValidationError as error:
            detail = error.messages[0]
            return Response({"detail": detail}, status=429 if "limit" in detail.lower() else 400)
        response = Response({
            "whatsapp_delivery": whatsapp_delivery,
            "created": True,
            "status": "pending",
            "phone": _mask_phone(party.phone),
            "setup_url": link,
            "expires_at": invite.expires_at,
            "email_sent_to": party.email,
            "email_delivery": delivery_status,
            **invite_policy_data(invite),
            **_staff_otp_fields(request, party),
        }, status=201)
        response["Cache-Control"] = "no-store, private"
        return response

    def _otp_display_disabled(self):
        return Response({
            "detail": "Showing verification codes in the CRM is not configured (PORTAL_OTP_ENCRYPTION_KEY). "
                      "The customer receives the code by email.",
            "code": "otp_copy_disabled",
        }, status=503)

    @action(detail=True, methods=["get"], url_path="portal-otp")
    def portal_otp(self, request, pk=None):
        """
        The customer's one ACTIVE portal code (portal.manage only). 404 when
        no code currently works -- for the full history, see portal-otps.
        """
        party = self.get_object()
        if not otp_vault.is_enabled():
            response = self._otp_display_disabled()
        else:
            row, code = current_staff_otp(party)
            if not code:
                response = Response({
                    "detail": "There is no active verification code for this customer. "
                              "It may have been used or expired; the customer can request a new one from their link.",
                    "code": "otp_unavailable",
                }, status=404)
            else:
                log_otp_disclosure(request, party, 1)
                now = timezone.now()
                response = Response({
                    "otp": code,
                    "otp_message_id": row["message_id"],
                    "otp_issued_at": row["issued_at"],
                    "otp_expires_at": row["expires_at"],
                    "otp_expires_in": max(0, int((row["expires_at"] - now).total_seconds())),
                    "server_time": now,
                })
        response["Cache-Control"] = "no-store, private"
        return response

    @action(detail=True, methods=["get"], url_path="portal-otps")
    def portal_otp_history(self, request, pk=None):
        """
        Every verification code issued to this customer (portal.manage only),
        each tied to its own CRM email-history entry, with a status of
        active / used / superseded / locked / expired / revoked. Reading a
        code here never makes it valid again -- verification only checks
        the current hashed code. Each read is recorded in PortalOtpAccessLog.
        """
        party = self.get_object()
        if not otp_vault.is_enabled():
            response = self._otp_display_disabled()
        else:
            rows = otp_history(party)
            log_otp_disclosure(request, party, sum(1 for row in rows if row["otp"]))
            response = Response({"otps": rows, "server_time": timezone.now()})
        response["Cache-Control"] = "no-store, private"
        return response

    @action(detail=True, methods=["post"], url_path="portal-reset-link")
    def portal_reset_link(self, request, pk=None):
        party = self.get_object()
        if not PortalInvite.objects.filter(party=party).exists():
            return Response({"detail": "Create the customer portal account first."}, status=400)
        try:
            invite, link, delivery_status, whatsapp_delivery = _issue_portal_invite(party, request)
        except ValidationError as error:
            detail = error.messages[0]
            return Response({"detail": detail}, status=429 if "limit" in detail.lower() else 400)
        response = Response({
            "whatsapp_delivery": whatsapp_delivery,
            "reset_url": link, "expires_at": invite.expires_at, "email_sent_to": party.email,
            "email_delivery": delivery_status, **invite_policy_data(invite), **_staff_otp_fields(request, party),
        }, status=201)
        response["Cache-Control"] = "no-store, private"
        return response

    @action(detail=True, methods=["post"], url_path="recheck-whatsapp")
    def recheck_whatsapp(self, request, pk=None):
        """Manual re-run of the Task 3 check -- for when staff has just
        confirmed a corrected number with the customer over a call and
        doesn't want to re-save the whole party record to trigger it."""
        party = self.get_object()
        result = _check_and_record_whatsapp(party)
        return Response({
            "whatsapp_verified": party.whatsapp_verified,
            "whatsapp_checked_at": party.whatsapp_checked_at,
            "reason": result.get("reason"),
        })

    @action(detail=True, methods=["post"], url_path="revoke-portal-access")
    def revoke_portal_access(self, request, pk=None):
        """
        Task 6 security checklist: portal tokens are stateless (no
        server-side session to delete), so "revoke access right now"
        works by stamping this moment on the party -- any token issued
        before it stops resolving immediately, even if it hasn't
        naturally expired yet. See portal.auth.resolve_portal_token.

        Invitation links are reusable until they expire, so the party's
        open links are revoked too -- otherwise the customer could simply
        log in again from the old link.
        """
        party = self.get_object()
        with transaction.atomic():
            party.portal_access_revoked_at = timezone.now()
            party.save(update_fields=["portal_access_revoked_at"])
            revoke_open_invites(party)
        return Response({"portal_access_revoked_at": party.portal_access_revoked_at})

    @action(detail=True, methods=["post"], url_path="message")
    def send_message(self, request, pk=None):
        """Save a thread message; a WhatsApp or email one is also sent (see _save_outbound_message)."""
        party = self.get_object()
        serializer = MessageRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = _save_outbound_message(serializer, party)
        return Response(MessageRecordSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageRecordViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    serializer_class = MessageRecordSerializer
    required_perms = {
        "create": "parties.manage", "update": "parties.manage", "partial_update": "parties.manage",
        "hide": "parties.view", "delete_for_everyone": "parties.manage",
        "retry": "parties.manage",
    }

    def get_queryset(self):
        return Message.objects.filter(party_id=self.kwargs["party_pk"]).select_related("party")

    def get_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def create(self, request, *args, **kwargs):
        party = Party.objects.filter(pk=self.kwargs["party_pk"]).first()
        if not party:
            return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = _save_outbound_message(serializer, party)
        # 201 even when the WhatsApp/email send failed: the message IS saved, and
        # its delivery_status/delivery_error say what happened
        return Response(self.get_serializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def retry(self, request, party_pk=None, pk=None):
        """Resend a failed WhatsApp message -- the same row, never a copy.
        An uncertain outcome (timeout) needs {"confirm": true}, because
        Meta may already have accepted it."""
        message = self.get_object()
        try:
            message = party_whatsapp.claim_for_retry(message, confirm_uncertain=request.data.get("confirm") is True)
        except party_whatsapp.RetryRefused as refused:
            return Response({"detail": refused.detail, "code": refused.code}, status=409)
        message = party_whatsapp.deliver(message)
        return Response(self.get_serializer(message).data)

    def update(self, request, *args, **kwargs):
        # PUT goes through the same guards as PATCH; only the body is editable.
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if "channel" in request.data:
            return Response({"detail": "The channel of a saved message cannot be changed."}, status=400)
        with transaction.atomic():
            message = Message.objects.select_for_update().filter(party_id=self.kwargs["party_pk"], pk=self.kwargs["pk"]).first()
            if not message:
                return Response({"detail": "Message not found."}, status=404)
            if not message.is_editable or message.deleted_at:
                return Response({"detail": "This historical message cannot be edited."}, status=409)
            if message.channel != Message.WHATSAPP:
                return Response({"detail": "Email history is copy-only."}, status=409)
            if message.delivery_status in (Message.DELIVERY_SENDING, Message.DELIVERY_UNKNOWN):
                return Response({"detail": "This message may already have reached WhatsApp, so it can't be edited."}, status=409)
            serializer = self.get_serializer(message, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            if "body" in serializer.validated_data:
                MessageRevision.objects.create(message=message, previous_body=message.body, edited_by=request.user)
                message.edited_at = timezone.now()
                serializer.save(edited_at=message.edited_at)
            else:
                serializer.save()
        return Response(self.get_serializer(message).data)

    @action(detail=True, methods=["post"])
    def hide(self, request, party_pk=None, pk=None):
        message = self.get_object()
        if message.channel != Message.WHATSAPP:
            return Response({"detail": "Email history is copy-only."}, status=409)
        MessageHidden.objects.get_or_create(message=message, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="delete-for-everyone")
    def delete_for_everyone(self, request, party_pk=None, pk=None):
        with transaction.atomic():
            message = Message.objects.select_for_update().filter(party_id=party_pk, pk=pk).first()
            if not message:
                return Response({"detail": "Message not found."}, status=404)
            if message.channel != Message.WHATSAPP:
                return Response({"detail": "Email history is copy-only."}, status=409)
            if not message.deleted_at:
                message.deleted_at = timezone.now()
                message.deleted_by = request.user
                message.save(update_fields=["deleted_at", "deleted_by"])
        return Response(self.get_serializer(message).data)
