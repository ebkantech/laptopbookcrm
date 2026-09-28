from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from accounts.throttling import OTPVerifyThrottle
from crmbook_backend.notify import notify_staff, send_email, send_whatsapp
from parties.models import Message, Party
from rentals.models import Rental
from repairs.models import RepairInvoice, RepairTicket
from sales.models import Invoice
from warranty.models import Warranty
from .auth import IsPortalCustomer, PortalTokenAuthentication, issue_portal_token
from .models import Feedback, PortalAccessLog, PortalInvite, WhatsAppDeliveryLog
from .serializers import (
    FeedbackSerializer, PortalAccessLogSerializer, PortalInvoiceSerializer, PortalInviteSerializer, PortalPartySerializer,
    PortalRentalSerializer, PortalRepairInvoiceSerializer, PortalRepairTicketSerializer, PortalWarrantySerializer,
)


def _client_ip(request):
    # standard reverse-proxy-aware extraction -- if this is ever
    # deployed behind Nginx (see the deployment notes elsewhere),
    # REMOTE_ADDR alone would just show the proxy's own IP
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _mask_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"


class PortalInviteViewSet(viewsets.ModelViewSet):
    """
    Staff-side: send a customer their portal link + OTP. Only ever
    for Rental-type parties right now -- the condition is enforced
    here, not just suggested in the UI.
    """
    queryset = PortalInvite.objects.select_related("party").all()
    serializer_class = PortalInviteSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "portal.manage"

    def create(self, request, *args, **kwargs):
        party = Party.objects.filter(pk=request.data.get("party")).first()
        if not party:
            return Response({"detail": "No such party."}, status=404)
        if party.type != Party.RENTAL:
            return Response({"detail": "Portal access is currently limited to rental customers."}, status=400)

        invite = PortalInvite.objects.create(party=party, issued_by=request.user)
        link = f"{settings.PUBLIC_FRONTEND_URL}/portal/{invite.token}"

        wa_body = f"Access your Vantage Computers portal here: {link}\nThis link expires in 30 minutes."
        Message.objects.create(party=party, channel=Message.WHATSAPP, direction=Message.OUT, body=wa_body)
        # Task 3: don't attempt a WhatsApp send to a number we've already
        # confirmed doesn't have WhatsApp -- email+OTP below is not
        # optional and covers this customer regardless. An unchecked
        # number (whatsapp_verified is None) still gets tried, since we
        # don't yet know either way.
        if party.whatsapp_verified is not False:
            wa_result = send_whatsapp(party.phone, wa_body)
            if wa_result.get("provider_id"):
                WhatsAppDeliveryLog.objects.create(
                    party=party, provider_message_id=wa_result["provider_id"],
                )

        email_body = f"Your one-time verification code is {invite.otp_code}. It expires in 30 minutes and can only be used once."
        Message.objects.create(party=party, channel=Message.EMAIL, direction=Message.OUT, body=email_body)
        send_email(party.email, "Your Vantage Computers portal verification code", email_body)

        return Response(PortalInviteSerializer(invite).data, status=201)


class PortalInviteStatusView(APIView):
    """
    Public (no auth) -- the customer hasn't logged in yet at this
    point. Lets the frontend show "enter the code sent to ****1234"
    and tell a genuinely expired/used link apart from a wrong OTP.

    authentication_classes is explicitly emptied (not just left to
    AllowAny) because DRF's default SessionAuthentication would
    otherwise still run and enforce CSRF on this endpoint -- and since
    the staff app and this portal share an origin/cookie-jar in
    single-server mode, a staff member who's also signed into the
    admin in the same browser would get a 403 here for a missing CSRF
    token, on a page their portal customer was never meant to need one
    for.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        invite = PortalInvite.objects.filter(token=token).select_related("party").first()
        if not invite:
            return Response({"detail": "This link is not valid."}, status=404)
        if not invite.is_valid:
            return Response({"detail": "This link has expired or was already used. Ask a staff member to send a new one."}, status=410)
        return Response({"party_name": invite.party.name, "masked_phone": _mask_phone(invite.party.phone)})


class PortalVerifyView(APIView):
    """
    Public -- the actual login step. Token from the link + OTP from the
    phone, both required.

    authentication_classes = [] for the same reason as
    PortalInviteStatusView above: this is a POST, so without it a
    staff member's leftover session cookie would trip DRF's CSRF
    check on this pre-login endpoint.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        token = request.data.get("token")
        otp = (request.data.get("otp") or "").strip()
        invite = PortalInvite.objects.filter(token=token).select_related("party").first()
        if not invite:
            return Response({"detail": "This link is not valid."}, status=404)
        if not invite.is_valid:
            return Response({"detail": "This link has expired or was already used. Ask a staff member to send a new one."}, status=410)
        if otp != invite.otp_code:
            return Response({"detail": "That code doesn't match. Check the message and try again."}, status=400)

        invite.consumed_at = timezone.now()
        invite.save(update_fields=["consumed_at"])

        # logged the moment a real login happens -- IP + user agent are
        # ordinary request metadata, no permission prompt involved
        log = PortalAccessLog.objects.create(
            party=invite.party, ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )

        return Response({
            "portal_token": issue_portal_token(invite.party),
            "party": PortalPartySerializer(invite.party).data,
            "access_log_id": log.id,
        })


class PortalLocationView(APIView):
    """
    Opt-in only. The portal's frontend calls this ONLY after the
    customer's browser has already shown its own native "allow this
    site to see your location?" prompt and they tapped Allow -- this
    endpoint just records whatever the browser handed back. There is
    no path to this data without that explicit, customer-facing
    permission dialog firing first.
    """
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def post(self, request):
        log_id = request.data.get("access_log_id")
        log = PortalAccessLog.objects.filter(pk=log_id, party=request.party).first()
        if not log:
            log = PortalAccessLog.objects.create(party=request.party, ip_address=_client_ip(request))
        log.latitude = request.data.get("latitude")
        log.longitude = request.data.get("longitude")
        log.location_accuracy_m = request.data.get("accuracy")
        log.save(update_fields=["latitude", "longitude", "location_accuracy_m"])
        return Response(PortalAccessLogSerializer(log).data)


class PortalAccessLogListView(APIView):
    """Staff-facing: a party's portal access history, for the Rentals/Parties screens."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "portal.manage"

    def get(self, request):
        party_id = request.query_params.get("party")
        qs = PortalAccessLog.objects.select_related("party").all()
        if party_id:
            qs = qs.filter(party_id=party_id)
        return Response(PortalAccessLogSerializer(qs, many=True).data)


class WhatsAppDeliveryWebhookView(APIView):
    """
    Task 3's delivery-status half: a real WhatsApp Business API provider
    POSTs here when a message's status changes (sent -> delivered ->
    read, or failed). Not called by anything automatically today -- no
    provider is wired yet (Task 2's still-open decision) -- this exists
    so turning one on later is "point its webhook URL here", not "build
    this endpoint too".

    The caller is an external provider, not a logged-in customer or
    staff member, so this is authenticated by a shared secret rather
    than IsPortalCustomer/staff JWT. WHATSAPP_WEBHOOK_SECRET must be set
    in the environment before this accepts anything -- unset (the
    default) means every request is refused, which is the safe default.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        expected = settings.WHATSAPP_WEBHOOK_SECRET
        provided = request.headers.get("X-Webhook-Secret") or request.data.get("secret")
        if not expected or provided != expected:
            return Response({"detail": "Invalid or missing webhook secret."}, status=403)

        provider_message_id = request.data.get("provider_message_id")
        status_value = request.data.get("status")
        valid_statuses = dict(WhatsAppDeliveryLog.STATUS_CHOICES)
        if not provider_message_id or status_value not in valid_statuses:
            return Response({"detail": "provider_message_id and a valid status are required."}, status=400)

        updated = WhatsAppDeliveryLog.objects.filter(provider_message_id=provider_message_id).update(
            status=status_value, detail=request.data.get("detail", ""),
        )
        return Response({"updated": updated})


class PortalMeView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        return Response(PortalPartySerializer(request.party).data)


class PortalInvoicesView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        qs = Invoice.objects.filter(party=request.party).prefetch_related("items__variant__product")
        return Response(PortalInvoiceSerializer(qs, many=True).data)


class PortalRepairsView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        tickets = RepairTicket.objects.filter(party=request.party).prefetch_related("services")
        invoices = RepairInvoice.objects.filter(ticket__party=request.party).select_related("ticket")
        return Response({
            "tickets": PortalRepairTicketSerializer(tickets, many=True).data,
            "invoices": PortalRepairInvoiceSerializer(invoices, many=True).data,
        })


class PortalRentalsView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        qs = Rental.objects.filter(party=request.party)
        return Response(PortalRentalSerializer(qs, many=True).data)


class PortalWarrantiesView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        qs = Warranty.objects.filter(party=request.party)
        return Response(PortalWarrantySerializer(qs, many=True).data)


class PortalFeedbackView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        qs = Feedback.objects.filter(party=request.party)
        return Response(FeedbackSerializer(qs, many=True).data)

    def post(self, request):
        serializer = FeedbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save(party=request.party)
        # Task 2: a low rating is the one feedback outcome worth an
        # internal alert -- who actually gets it is configured on
        # Settings > Staff alerts, not hardcoded here.
        if feedback.rating <= 2:
            notify_staff(
                "low_negative_feedback",
                f"Low rating from {request.party.name} ({feedback.rating}/5)",
                f"{request.party.name} left {feedback.rating}/5 feedback on their portal"
                + (f": “{feedback.comment}”" if feedback.comment else " (no comment left)."),
            )
        return Response(serializer.data, status=201)
