from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from crmbook_backend.notify import check_whatsapp_number, send_email, send_whatsapp
from portal.models import PortalAccessLog, PortalInvite, WhatsAppDeliveryLog

from .models import Message, Party
from .serializers import MessageSerializer, PartyDetailSerializer, PartySerializer


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


def _issue_portal_invite(party, request):
    """
    Shared by portal-invite and portal-reset-link: the token-based portal
    has no password to reset, so "resend a link" and "reset access" are the
    same action underneath -- a fresh 30-minute link + OTP, exactly like
    PortalInviteViewSet.create in the portal app.

    Task 3's fallback path: a party flagged whatsapp_verified=False (a
    known-bad number, not just "not checked yet") skips the WhatsApp send
    attempt entirely -- the email+OTP path below is not optional and
    always runs, so the customer can still get in even when WhatsApp
    delivery isn't possible.
    """
    invite = PortalInvite.objects.create(party=party, issued_by=request.user)
    link = f"{settings.PUBLIC_FRONTEND_URL}/portal/{invite.token}"

    if party.whatsapp_verified is not False:
        wa_body = f"Access your Vantage Computers portal here: {link}\nThis link expires in 30 minutes."
        Message.objects.create(party=party, channel=Message.WHATSAPP, direction=Message.OUT, body=wa_body)
        result = send_whatsapp(party.phone, wa_body)
        # A provider_id means the provider accepted the message and might
        # later post a delivery-status webhook against it -- nothing to
        # track when it was skipped/failed outright.
        if result.get("provider_id"):
            WhatsAppDeliveryLog.objects.create(
                party=party, provider_message_id=result["provider_id"], status=WhatsAppDeliveryLog.SENT,
            )

    email_body = f"Your one-time verification code is {invite.otp_code}. It expires in 30 minutes and can only be used once."
    Message.objects.create(party=party, channel=Message.EMAIL, direction=Message.OUT, body=email_body)
    send_email(party.email, "Your Vantage Computers portal verification code", email_body)

    return invite, link


class PartyViewSet(viewsets.ModelViewSet):
    queryset = Party.objects.prefetch_related("invoices__items", "invoices__stock_point", "messages").all()
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "parties.view", "retrieve": "parties.view",
        "create": "parties.manage", "update": "parties.manage",
        "partial_update": "parties.manage", "destroy": "parties.manage",
        "portal_account": "parties.view",
        "portal_invite": "parties.manage", "portal_reset_link": "parties.manage",
        "send_message": "parties.manage",
        "recheck_whatsapp": "parties.manage",
        "revoke_portal_access": "parties.manage",
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
        status = "active" if latest_log else ("pending" if latest_invite.is_valid else "expired")
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
        if party.type != Party.RENTAL:
            return Response({"detail": "Portal access is currently limited to rental customers."}, status=400)
        invite, link = _issue_portal_invite(party, request)
        response = Response({
            "created": True,
            "status": "pending",
            "phone": _mask_phone(party.phone),
            "setup_url": link,
            "expires_at": invite.expires_at,
        }, status=201)
        response["Cache-Control"] = "no-store, private"
        return response

    @action(detail=True, methods=["post"], url_path="portal-reset-link")
    def portal_reset_link(self, request, pk=None):
        party = self.get_object()
        if not PortalInvite.objects.filter(party=party).exists():
            return Response({"detail": "Create the customer portal account first."}, status=400)
        invite, link = _issue_portal_invite(party, request)
        response = Response({"reset_url": link, "expires_at": invite.expires_at}, status=201)
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
        """
        party = self.get_object()
        party.portal_access_revoked_at = timezone.now()
        party.save(update_fields=["portal_access_revoked_at"])
        return Response({"portal_access_revoked_at": party.portal_access_revoked_at})

    @action(detail=True, methods=["post"], url_path="message")
    def send_message(self, request, pk=None):
        party = self.get_object()
        channel = request.data.get("channel", "whatsapp")
        body = request.data["body"]
        msg = Message.objects.create(party=party, channel=channel, direction="out", body=body)
        if channel == Message.EMAIL:
            send_email(party.email, f"Message from Vantage Computers", body)
        else:
            send_whatsapp(party.phone, body)
        return Response(MessageSerializer(msg).data, status=201)
