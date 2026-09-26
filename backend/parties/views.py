from django.conf import settings
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsStaffAccount
from portal.models import PortalAccessLog, PortalInvite

from .models import Message, Party
from .serializers import MessageSerializer, PartyDetailSerializer, PartySerializer


def _mask_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"


def _issue_portal_invite(party, request):
    """
    Shared by portal-invite and portal-reset-link: the token-based portal
    has no password to reset, so "resend a link" and "reset access" are the
    same action underneath -- a fresh 30-minute link + OTP, exactly like
    PortalInviteViewSet.create in the portal app.
    """
    invite = PortalInvite.objects.create(party=party, issued_by=request.user)
    link = f"{settings.PUBLIC_FRONTEND_URL}/portal/{invite.token}"
    Message.objects.create(
        party=party, channel=Message.WHATSAPP, direction=Message.OUT,
        body=f"Access your Vantage Computers portal here: {link}\nThis link expires in 30 minutes.",
    )
    Message.objects.create(
        party=party, channel=Message.EMAIL, direction=Message.OUT,
        body=f"Your one-time verification code is {invite.otp_code}. It expires in 30 minutes and can only be used once.",
    )
    return invite, link


class PartyViewSet(viewsets.ModelViewSet):
    queryset = Party.objects.prefetch_related("invoices__items", "invoices__stock_point", "messages").all()
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    def get_serializer_class(self):
        return PartyDetailSerializer if self.action == "retrieve" else PartySerializer

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

    @action(detail=True, methods=["post"], url_path="message")
    def send_message(self, request, pk=None):
        party = self.get_object()
        msg = Message.objects.create(
            party=party, channel=request.data.get("channel", "whatsapp"),
            direction="out", body=request.data["body"],
        )
        return Response(MessageSerializer(msg).data, status=201)
