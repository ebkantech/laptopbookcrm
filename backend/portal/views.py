import os
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, HttpResponse
from django.core.exceptions import ValidationError
from rest_framework import permissions, viewsets
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from accounts.throttling import OTPResendInviteThrottle, OTPResendThrottle, OTPVerifyThrottle, PortalIssueThrottle, PortalMessageThrottle, PortalPdfThrottle
from crmbook_backend.notify import notify_staff
from parties.models import Message, Party
from rentals.models import Rental, RentalIssue
from repairs.models import RepairTicket
from sales.documents import pdf_available, render_invoice_pdf
from sales.models import Invoice
from warranty.models import Warranty
from .auth import IsPortalCustomer, PortalTokenAuthentication, issue_portal_token
from .models import Feedback, PortalAccessLog, PortalInvite, WhatsAppDeliveryLog
from .serializers import (
    PortalIssueSerializer,
    FeedbackSerializer, PortalAccessLogSerializer, PortalInvoiceDetailSerializer, PortalInvoiceSerializer, PortalInviteSerializer,
    PortalPartySerializer,
    PortalRentalSerializer, PortalRepairInvoiceSerializer, PortalRepairTicketSerializer, PortalWarrantySerializer,
)
from . import access
from .services import (
    CLOSED_MESSAGES, PortalFlowError, create_portal_invite, current_staff_otp, invite_policy_data, invite_status_data,
    log_otp_disclosure,
    invite_whatsapp_body,
    resend_otp, send_invite_whatsapp, verify_otp,
)


def _client_ip(request):
    # standard reverse-proxy-aware extraction -- if this is ever
    # deployed behind Nginx (see the deployment notes elsewhere),
    # REMOTE_ADDR alone would just show the proxy's own IP
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _flow_error(error):
    response = Response(error.as_data(), status=error.status)
    if error.status == 429 and error.extra.get("retry_after"):
        response["Retry-After"] = str(error.extra["retry_after"])
    return response


def _body_token(request):
    """The invitation token from a JSON body, or a 400 Response when it isn't a well-formed link token."""
    raw = request.data.get("token") if hasattr(request.data, "get") else None
    try:
        return uuid.UUID(str(raw or "").strip()), None
    except ValueError:
        return None, Response({"detail": "A valid invitation token is required.", "code": "invalid_request"}, status=400)


class _CodedThrottleMixin:
    """Adds a stable `code` and `retry_after` to DRF's throttled 429 (which already sets Retry-After)."""
    throttle_code = "throttled"

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if isinstance(exc, Throttled) and isinstance(response.data, dict):
            response.data["code"] = self.throttle_code
            if exc.wait is not None:
                response.data["retry_after"] = int(exc.wait)
        return response


class PortalInviteViewSet(viewsets.ModelViewSet):
    """
    Staff-side: send a customer their portal link + OTP. Any customer
    type: Rental links last until the end of the rental tenure (and need
    a running agreement), Dealer/Retail links last 24 hours -- see
    portal.access.
    """
    queryset = PortalInvite.objects.select_related("party").all()
    serializer_class = PortalInviteSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "portal.manage"

    def create(self, request, *args, **kwargs):
        party = Party.objects.filter(pk=request.data.get("party")).first()
        if not party:
            return Response({"detail": "No such party."}, status=404)

        try:
            invite, delivery_status = create_portal_invite(party, request.user)
        except ValidationError as error:
            return Response({"detail": error.messages[0]}, status=429 if "limit" in error.messages[0].lower() else 400)
        link = f"{settings.PUBLIC_FRONTEND_URL}/portal/{invite.token}"

        wa_body = invite_whatsapp_body(invite, link)
        Message.objects.create(party=party, channel=Message.WHATSAPP, direction=Message.OUT, body=wa_body)
        # Task 3: a number already confirmed not to have WhatsApp is
        # skipped -- email+OTP below is not optional and covers this
        # customer regardless. An unchecked number (whatsapp_verified is
        # None) still gets tried, since we don't yet know either way.
        whatsapp_delivery = send_invite_whatsapp(party, invite, link)

        data = PortalInviteSerializer(invite).data
        data["email_delivery"] = delivery_status
        data["whatsapp_delivery"] = whatsapp_delivery
        data.update(invite_policy_data(invite))
        # this endpoint already requires portal.manage
        current, code = current_staff_otp(party)
        if code:
            log_otp_disclosure(request, party, 1)
            data["otp"], data["otp_message_id"] = code, current["message_id"]
        response = Response(data, status=201)
        response["Cache-Control"] = "no-store, private"
        return response


class PortalInviteStatusView(APIView):
    """
    Public (no auth) -- the customer hasn't logged in yet at this
    point. Lets the frontend show a masked email address, the link and code
    expiry, the resend cooldown, and tell an expired/revoked link apart
    from a wrong or expired code. A link that has already been used to
    log in stays valid here until it expires.

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
            return Response({"detail": "This link is not valid.", "code": "invite_invalid"}, status=404)
        closed = access.invite_closed_code(invite)
        if closed:
            return _flow_error(PortalFlowError(closed, CLOSED_MESSAGES[closed], 410))
        response = Response(invite_status_data(invite))
        response["Cache-Control"] = "no-store, private"
        return response


class PortalVerifyView(_CodedThrottleMixin, APIView):
    """
    Public -- the actual login step. Token from the link + OTP from the
    customer's email, both required. A correct code is single-use; the
    link itself stays usable until it expires (portal.services.verify_otp).

    authentication_classes = [] for the same reason as
    PortalInviteStatusView above: this is a POST, so without it a
    staff member's leftover session cookie would trip DRF's CSRF
    check on this pre-login endpoint.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPVerifyThrottle]
    throttle_code = "verify_throttled"

    def post(self, request):
        token, bad_request = _body_token(request)
        if bad_request:
            return bad_request
        otp = str(request.data.get("otp") or "").strip()
        if not (len(otp) == 6 and otp.isdigit()):
            return Response({"detail": "Enter the 6-digit code from the email.", "code": "invalid_request"}, status=400)
        try:
            invite = verify_otp(token, otp)
        except PortalFlowError as error:
            return _flow_error(error)

        # logged the moment a real login happens -- IP + user agent are
        # ordinary request metadata, no permission prompt involved
        log = PortalAccessLog.objects.create(
            party=invite.party, ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )

        response = Response({
            "portal_token": issue_portal_token(invite.party),
            "party": PortalPartySerializer(invite.party).data,
            "access_log_id": log.id,
        })
        response["Cache-Control"] = "no-store, private"
        return response


class PortalResendOtpView(_CodedThrottleMixin, APIView):
    """
    Public -- "send me a new code" from a still-valid invitation link.
    Replaces (and so invalidates) the previous code, emails the new one,
    and never extends or revives the link itself. Pre-login, so no
    authentication/CSRF for the same reason as PortalVerifyView.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPResendThrottle, OTPResendInviteThrottle]
    throttle_code = "resend_throttled"

    def post(self, request):
        token, bad_request = _body_token(request)
        if bad_request:
            return bad_request
        try:
            invite = resend_otp(token)
        except PortalFlowError as error:
            return _flow_error(error)
        data = invite_status_data(invite)
        response = Response({
            "detail": "A new verification code has been sent to your registered email address.",
            "masked_email": data["masked_email"],
            "otp_expires_in": data["otp_expires_in"],
            "otp_expires_at": data["otp_expires_at"],
            "server_time": data["server_time"],
            "resend_available_in": data["resend_available_in"],
            "invite_expires_at": data["invite_expires_at"],
        })
        response["Cache-Control"] = "no-store, private"
        return response


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


def _own_invoices(request):
    """Every portal invoice lookup starts here: scoped to the session's party, never to an id the client sends."""
    return (
        Invoice.objects.filter(party=request.party)
        .select_related("stock_point", "party", "repair_ticket", "rental")
        .prefetch_related("items__variant__product", "refunds", "payment_links")
    )


def _no_such_invoice():
    # identical for "doesn't exist" and "belongs to someone else" -- no existence leak
    return Response({"detail": "Invoice not found.", "code": "invoice_not_found"}, status=404)


class PortalInvoicesView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        return Response(PortalInvoiceSerializer(_own_invoices(request), many=True).data)


class PortalInvoiceDetailView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request, invoice_id):
        invoice = _own_invoices(request).filter(pk=invoice_id).first()
        if not invoice:
            return _no_such_invoice()
        return Response(PortalInvoiceDetailSerializer(invoice).data)


class PortalInvoicePdfView(APIView):
    """
    The customer's own invoice as a PDF, rendered on request from the
    invoice record (sales.documents -- the same document staff print).
    Nothing is read from a client-supplied path or URL and no stored-file
    URL is ever exposed. Served at both .../pdf/ and .../download/.
    """
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]
    throttle_classes = [PortalPdfThrottle]

    def perform_content_negotiation(self, request, force=False):
        # the portal sends "Accept: application/pdf"; errors still go out as JSON
        return super().perform_content_negotiation(request, force=True)

    def get(self, request, invoice_id):
        invoice = _own_invoices(request).filter(pk=invoice_id).first()
        if not invoice:
            return _no_such_invoice()
        if not pdf_available(invoice):
            return Response({"detail": "This invoice has no lines to print yet.", "code": "pdf_unavailable"}, status=404)
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", f"Invoice-{invoice.code}").strip("-.") + ".pdf"
        response = HttpResponse(render_invoice_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PortalRepairsView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        tickets = RepairTicket.objects.filter(party=request.party).select_related("stock_point").prefetch_related("services")
        invoices = Invoice.objects.filter(party=request.party, source=Invoice.REPAIR).select_related("repair_ticket").prefetch_related("payment_links").prefetch_related("items")
        return Response({
            "tickets": PortalRepairTicketSerializer(tickets, many=True).data,
            "invoices": PortalRepairInvoiceSerializer(invoices, many=True).data,
        })


class PortalRentalsView(APIView):
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]

    def get(self, request):
        # drafts are staff working copies the customer has never been shown
        qs = (
            Rental.objects.filter(party=request.party).exclude(status=Rental.DRAFT)
            .select_related("party").prefetch_related("lines__asset")
        )
        return Response(PortalRentalSerializer(qs, many=True).data)


class PortalSignedAgreementView(APIView):
    """The signed copy of the customer's own agreement. It is looked up within
    request.party and streamed from here: no stored-file URL is ever exposed."""
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]
    throttle_classes = [PortalPdfThrottle]

    def perform_content_negotiation(self, request, force=False):
        # the file isn't JSON; errors still go out as JSON
        return super().perform_content_negotiation(request, force=True)

    def get(self, request, rental_id):
        rental = Rental.objects.filter(pk=rental_id, party=request.party).exclude(status=Rental.DRAFT).first()
        if not rental or not rental.signed_agreement:
            return Response({"detail": "No signed copy of this agreement is on file.", "code": "agreement_not_found"}, status=404)
        ext = os.path.splitext(rental.signed_agreement.name)[1]
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", rental.agreement_code or f"Agreement-{rental.pk}").strip("-.")
        response = FileResponse(rental.signed_agreement.open("rb"), content_type=rental.signed_content_type)
        response["Content-Disposition"] = f'attachment; filename="{label}-signed{ext}"'
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PortalIssuesView(APIView):
    """
    Issues a customer raises about their rented laptop. They land in the same
    list staff work from on the rental. The agreement is always looked up
    within request.party, so one customer can't reach another's.
    """
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]
    MAX_DESCRIPTION = 2000

    def get_throttles(self):
        return [PortalIssueThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        issues = RentalIssue.objects.filter(rental__party=request.party).select_related("rental")
        return Response(PortalIssueSerializer(issues, many=True).data)

    def post(self, request):
        title = str(request.data.get("title") or "").strip()
        description = str(request.data.get("description") or "").strip()
        if not title:
            return Response({"detail": "Tell us briefly what the problem is."}, status=400)
        if len(title) > RentalIssue._meta.get_field("title").max_length:
            return Response({"detail": "Keep the summary short. Add the details below it."}, status=400)
        if len(description) > self.MAX_DESCRIPTION:
            return Response({"detail": f"Keep the details under {self.MAX_DESCRIPTION:,} characters."}, status=400)
        rental_id = request.data.get("rental")
        rental = None
        if str(rental_id or "").isdigit():
            rental = Rental.objects.filter(
                pk=int(rental_id), party=request.party, status__in=access.QUALIFYING_RENTAL_STATUSES,
            ).first()
        if rental is None:
            return Response({"detail": "Choose one of your running rental agreements."}, status=400)
        with transaction.atomic():
            issue = RentalIssue.objects.create(rental=rental, title=title, description=description)
            Rental.objects.filter(pk=rental.pk).update(tickets=F("tickets") + 1)
        return Response(PortalIssueSerializer(issue).data, status=201)


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


class PortalMessagesView(APIView):
    """
    Customer portal chat. A customer reads and writes only their own party's
    portal thread (request.party, never a value from the request), and only
    staff answer: nothing automated replies here. See docs/COPILOT.md.
    """
    authentication_classes = [PortalTokenAuthentication]
    permission_classes = [IsPortalCustomer]
    MAX_LENGTH = 2000

    def get_throttles(self):
        return [PortalMessageThrottle()] if self.request.method == "POST" else []

    def _row(self, message):
        return {"id": message.id, "direction": message.direction, "body": message.body, "at": message.at}

    def get(self, request):
        rows = Message.objects.filter(party=request.party, channel=Message.PORTAL, deleted_at__isnull=True).order_by("-at", "-id")[:100]
        return Response([self._row(row) for row in reversed(rows)])

    def post(self, request):
        body = str(request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Type a message first."}, status=400)
        if len(body) > self.MAX_LENGTH:
            return Response({"detail": f"Keep messages under {self.MAX_LENGTH:,} characters."}, status=400)
        message = Message.objects.create(party=request.party, channel=Message.PORTAL, direction=Message.IN, body=body)
        return Response(self._row(message), status=201)
