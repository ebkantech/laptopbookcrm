from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Prefetch
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from rentals.models import Rental, RentalApproval
from repairs.models import RepairApproval, RepairOrderApproval, RepairTicket

from .approval_services import decide_repair, decide_repair_order, decide_rental
from .models import CustomerAccessToken, CustomerLoginEvent, CustomerProfile
from .permissions import IsActiveCustomer
from .serializers import (
    CustomerDecisionSerializer,
    CustomerLoginSerializer,
    CustomerPasswordSerializer,
    PortalRentalSerializer,
    PortalRepairTicketSerializer,
)
from .services import access_summary, get_access_token
from .throttling import CustomerLoginRateThrottle, CustomerTokenRateThrottle
from .utils import client_ip, identifier_hash, mask_phone


DUMMY_PASSWORD_HASH = make_password("crmbook-customer-dummy-password")


def _private(response):
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    return response


def _audit(request, event_type, profile=None, identifier=""):
    CustomerLoginEvent.objects.create(
        profile=profile,
        event_type=event_type,
        identifier_hash=identifier_hash(identifier) if identifier else "",
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )


def _delete_user_sessions(user):
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        data = session.get_decoded()
        if str(data.get("_auth_user_id")) == str(user.pk):
            session.delete()


def _profile_payload(profile):
    memberships = list(profile.memberships.select_related("party").all())
    return {
        "id": profile.id,
        "name": profile.user.get_full_name() or memberships[0].party.name,
        "phone": mask_phone(profile.phone_e164),
        "status": profile.status,
        "parties": [
            {
                "id": row.party_id,
                "name": row.party.name,
                "classification": row.party.customer_classification,
                "role": row.role,
            }
            for row in memberships
        ],
        "access": access_summary(profile),
        "brand": {
            "name": getattr(settings, "CUSTOMER_PORTAL_BRAND_NAME", "Vantage Computers"),
            "support_phone": getattr(settings, "CUSTOMER_PORTAL_SUPPORT_PHONE", ""),
            "support_email": getattr(settings, "CUSTOMER_PORTAL_SUPPORT_EMAIL", ""),
        },
    }


class CustomerCsrfView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return _private(Response({"csrf_token": get_token(request)}))


@method_decorator(csrf_protect, name="dispatch")
class CustomerLoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CustomerLoginRateThrottle]

    def post(self, request):
        serializer = CustomerLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        password = serializer.validated_data["password"]
        profile = CustomerProfile.objects.select_related("user").filter(phone_e164=phone).first()
        now = timezone.now()

        if profile is None:
            check_password(password, DUMMY_PASSWORD_HASH)
            _audit(request, CustomerLoginEvent.LOGIN_FAILURE, identifier=phone)
            return Response({"detail": "Unable to sign in with those credentials."}, status=400)
        if profile.locked_until and profile.locked_until > now:
            _audit(request, CustomerLoginEvent.LOGIN_FAILURE, profile=profile, identifier=phone)
            return Response({"detail": "Sign-in is temporarily unavailable. Please try again later."}, status=429)

        user = authenticate(request, username=profile.user.username, password=password)
        if user is None or profile.status != CustomerProfile.ACTIVE:
            profile.failed_login_attempts += 1
            fields = ["failed_login_attempts"]
            if profile.failed_login_attempts >= 5:
                profile.locked_until = now + timedelta(minutes=15)
                fields.append("locked_until")
            profile.save(update_fields=fields)
            _audit(request, CustomerLoginEvent.LOGIN_FAILURE, profile=profile, identifier=phone)
            return Response({"detail": "Unable to sign in with those credentials."}, status=400)

        access = access_summary(profile)
        if access["mode"] == "expired":
            _audit(request, CustomerLoginEvent.LOGIN_FAILURE, profile=profile, identifier=phone)
            return Response({"detail": "Your portal access period has ended. Please contact support."}, status=403)

        profile.failed_login_attempts = 0
        profile.locked_until = None
        profile.save(update_fields=["failed_login_attempts", "locked_until"])
        login(request, user)
        request.session.cycle_key()
        request.session["customer_authenticated_at"] = now.timestamp()
        request.session["customer_last_activity"] = now.timestamp()
        request.session.set_expiry(int(getattr(settings, "CUSTOMER_PORTAL_SESSION_SECONDS", 28800)))
        _audit(request, CustomerLoginEvent.LOGIN_SUCCESS, profile=profile, identifier=phone)
        return _private(Response(_profile_payload(profile)))


@method_decorator(csrf_protect, name="dispatch")
class CustomerLogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveCustomer]

    def post(self, request):
        profile = request.user.customer_profile
        _audit(request, CustomerLoginEvent.LOGOUT, profile=profile)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class CustomerTokenBaseView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CustomerTokenRateThrottle]
    purpose = None

    def get(self, request, token):
        access_token = get_access_token(token, self.purpose)
        party = access_token.profile.memberships.select_related("party").first().party
        return _private(Response({
            "customer_name": party.name,
            "phone": mask_phone(access_token.profile.phone_e164),
            "expires_at": access_token.expires_at,
            "purpose": self.purpose,
        }))

    def post(self, request, token):
        with transaction.atomic():
            access_token = get_access_token(token, self.purpose, for_update=True)
            profile = CustomerProfile.objects.select_for_update().select_related("user").get(pk=access_token.profile_id)
            serializer = CustomerPasswordSerializer(data=request.data, context={"user": profile.user})
            serializer.is_valid(raise_exception=True)
            if serializer.validated_data["phone"] != profile.phone_e164:
                return Response({"detail": "The phone number does not match this customer invitation."}, status=400)
            profile.user.set_password(serializer.validated_data["password"])
            profile.user.save(update_fields=["password"])
            event_type = CustomerLoginEvent.ACTIVATED
            if self.purpose == CustomerAccessToken.ACTIVATION:
                profile.status = CustomerProfile.ACTIVE
                profile.activated_at = timezone.now()
                profile.failed_login_attempts = 0
                profile.locked_until = None
                profile.save(update_fields=["status", "activated_at", "failed_login_attempts", "locked_until"])
            else:
                _delete_user_sessions(profile.user)
                event_type = CustomerLoginEvent.PASSWORD_RESET
            access_token.consumed_at = timezone.now()
            access_token.save(update_fields=["consumed_at"])
            _audit(request, event_type, profile=profile)
        return _private(Response({"detail": "Password saved. You can now sign in."}))


class CustomerActivateView(CustomerTokenBaseView):
    purpose = CustomerAccessToken.ACTIVATION


class CustomerResetPasswordView(CustomerTokenBaseView):
    purpose = CustomerAccessToken.PASSWORD_RESET


class CustomerMeView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveCustomer]

    def get(self, request):
        return _private(Response(_profile_payload(request.user.customer_profile)))


class CustomerDashboardView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveCustomer]

    def get(self, request):
        profile = request.user.customer_profile
        access = access_summary(profile)
        if access["mode"] == "expired":
            raise PermissionDenied("Your portal access period has ended. Please contact support.")
        party_ids = list(profile.memberships.values_list("party_id", flat=True))
        rentals = Rental.objects.filter(party_id__in=party_ids).prefetch_related(
            "lines__asset", "issues", Prefetch("approvals", queryset=RentalApproval.objects.order_by("-version"))
        ).order_by("-start", "-id")
        repairs = RepairTicket.objects.filter(party_id__in=party_ids).select_related("order").prefetch_related(
            "estimates__lines", "estimates__approvals", "invoices", "events", "order__tickets"
        ).order_by("-received", "-id")
        order_approvals = RepairOrderApproval.objects.filter(order__party_id__in=party_ids).order_by("-created_at")
        pending_orders = [
            {
                "id": approval.id,
                "kind": "repair_order",
                "status": approval.effective_status,
                "expires_at": approval.expires_at,
                "snapshot": approval.snapshot,
            }
            for approval in order_approvals
            if approval.effective_status == RepairOrderApproval.PENDING
        ]
        return _private(Response({
            "profile": _profile_payload(profile),
            "rentals": PortalRentalSerializer(rentals, many=True).data,
            "repairs": PortalRepairTicketSerializer(repairs, many=True).data,
            "pending_order_approvals": pending_orders,
        }))


class CustomerApprovalDecisionBase(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveCustomer]
    model = None

    def post(self, request, pk):
        profile = request.user.customer_profile
        access = access_summary(profile)
        if not access["can_decide"]:
            raise PermissionDenied("Approvals are unavailable after the active service period ends.")
        serializer = CustomerDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = self.get_approval(profile, pk)
        decided = self.decide(approval, request.user, **serializer.validated_data)
        return _private(Response({
            "id": decided.id,
            "status": decided.effective_status,
            "source": decided.source,
            "decided_at": decided.decided_at,
        }))


class CustomerRentalApprovalDecisionView(CustomerApprovalDecisionBase):
    def get_approval(self, profile, pk):
        party_ids = profile.memberships.values_list("party_id", flat=True)
        return get_object_or_404(
            RentalApproval.objects.select_related("rental"),
            pk=pk,
            rental__party_id__in=party_ids,
        )

    def decide(self, approval, user, **data):
        return decide_rental(approval, actor=user, **data)


class CustomerRepairApprovalDecisionView(CustomerApprovalDecisionBase):
    def get_approval(self, profile, pk):
        party_ids = profile.memberships.values_list("party_id", flat=True)
        return get_object_or_404(
            RepairApproval.objects.select_related("estimate__ticket"),
            pk=pk,
            estimate__ticket__party_id__in=party_ids,
            order_approval__isnull=True,
        )

    def decide(self, approval, user, **data):
        return decide_repair(approval, actor=user, **data)


class CustomerRepairOrderApprovalDecisionView(CustomerApprovalDecisionBase):
    def get_approval(self, profile, pk):
        party_ids = profile.memberships.values_list("party_id", flat=True)
        return get_object_or_404(
            RepairOrderApproval.objects.select_related("order"),
            pk=pk,
            order__party_id__in=party_ids,
        )

    def decide(self, approval, user, **data):
        return decide_repair_order(approval, actor=user, **data)
