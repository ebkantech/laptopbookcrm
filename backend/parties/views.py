from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsStaffAccount
from customer_portal.models import CustomerAccessToken
from customer_portal.services import get_or_create_customer_profile, issue_access_token
from customer_portal.utils import mask_phone

from .models import Message, Party
from .serializers import MessageSerializer, PartyDetailSerializer, PartySerializer


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
        membership = party.portal_memberships.select_related("profile__user").first()
        if not membership:
            return Response({"enabled": False, "status": "not_created"})
        profile = membership.profile
        latest_token = profile.access_tokens.order_by("-created_at").first()
        return Response({
            "enabled": True,
            "status": profile.status,
            "phone": mask_phone(profile.phone_e164),
            "activated_at": profile.activated_at,
            "last_link": (
                {
                    "purpose": latest_token.purpose,
                    "created_at": latest_token.created_at,
                    "expires_at": latest_token.expires_at,
                    "usable": latest_token.is_usable,
                }
                if latest_token else None
            ),
        })

    @action(detail=True, methods=["post"], url_path="portal-invite")
    def portal_invite(self, request, pk=None):
        party = self.get_object()
        profile, created = get_or_create_customer_profile(
            party,
            created_by=request.user,
            phone=request.data.get("phone") or party.phone,
        )
        token, url = issue_access_token(profile, CustomerAccessToken.ACTIVATION, request.user)
        response = Response({
            "created": created,
            "status": profile.status,
            "phone": mask_phone(profile.phone_e164),
            "setup_url": url,
            "expires_at": token.expires_at,
        }, status=201)
        response["Cache-Control"] = "no-store, private"
        return response

    @action(detail=True, methods=["post"], url_path="portal-reset-link")
    def portal_reset_link(self, request, pk=None):
        party = self.get_object()
        membership = party.portal_memberships.select_related("profile").first()
        if not membership:
            return Response({"detail": "Create the customer portal account first."}, status=400)
        token, url = issue_access_token(
            membership.profile,
            CustomerAccessToken.PASSWORD_RESET,
            request.user,
        )
        response = Response({"reset_url": url, "expires_at": token.expires_at}, status=201)
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
