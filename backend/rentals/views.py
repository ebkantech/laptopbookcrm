import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.exceptions import MethodNotAllowed, ValidationError

from accounts.permissions import HasPerm
from .models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalIssue, RentalLine
from .serializers import (
    CreateRentalAgreementSerializer,
    PublicRentalApprovalDecisionSerializer,
    PublicRentalApprovalSerializer,
    RentalAssetSerializer,
    RentalIssueSerializer,
    RentalSerializer,
    StaffRentalApprovalSerializer,
)
from .services import (
    approve_on_behalf,
    cancel_agreement,
    close_agreement,
    customer_decide,
    issue_approval_link,
)


def _audit_value(value):
    if hasattr(value, "all") and hasattr(value, "values_list"):
        return list(value.values_list("pk", flat=True))
    if hasattr(value, "pk"):
        return value.pk
    return value


class RentalViewSet(viewsets.ModelViewSet):
    queryset = Rental.objects.select_related("party").prefetch_related("issues__assigned_to", "lines__asset", "approvals").all()
    serializer_class = RentalSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None,
        "create": "rentals.manage", "update": "rentals.manage",
        "partial_update": "rentals.manage", "destroy": "rentals.manage",
        "create_agreement": "rentals.manage", "approval_link": "rentals.manage",
        "approve_on_behalf": "rentals.approve", "cancel": "rentals.manage",
        "close": "rentals.manage",
    }

    def get_queryset(self):
        return super().get_queryset().order_by("-start")

    def list(self, request, *args, **kwargs):
        # highest churn risk first -- computed in Python since it isn't a stored column
        qs = sorted(self.filter_queryset(self.get_queryset()), key=lambda r: r.churn_score, reverse=True)
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def perform_update(self, serializer):
        rental = self.get_object()
        if rental.status == Rental.APPROVED:
            if not self.request.user.has_perm_code("rentals.approve"):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Only an Admin or Super Admin can change an approved rental agreement.")
            reason = (self.request.data.get("internal_change_reason") or "").strip()
            if not reason:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"internal_change_reason": "A reason is required after customer approval."})
            before = {field: _audit_value(getattr(rental, field)) for field in serializer.validated_data}
            updated = serializer.save()
            after = {field: _audit_value(getattr(updated, field)) for field in serializer.validated_data}
            if before != after:
                RentalEvent.objects.create(
                    rental=updated,
                    event_type=RentalEvent.MODIFIED_AFTER_APPROVAL,
                    actor=self.request.user,
                    metadata=json.loads(DjangoJSONEncoder().encode(
                        {"reason": reason, "before": before, "after": after}
                    )),
                )
            return
        serializer.save()

    @action(detail=False, methods=["post"], url_path="create-agreement")
    def create_agreement(self, request):
        payload = CreateRentalAgreementSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        with transaction.atomic():
            lines = data.pop("lines")
            rates_by_asset_id = {line["asset"].pk: line["monthly_fee"] for line in lines}
            asset_ids = list(rates_by_asset_id)
            locked_assets = list(
                RentalAsset.objects.select_for_update().filter(pk__in=asset_ids).order_by("pk")
            )
            if len(locked_assets) != len(asset_ids):
                raise ValidationError({"lines": "One or more selected assets no longer exist."})
            unavailable = [asset.asset_tag for asset in locked_assets if asset.status != RentalAsset.AVAILABLE]
            if unavailable:
                raise ValidationError({
                    "lines": f"Assets are no longer available: {', '.join(unavailable)}. Refresh and choose again."
                })
            first_asset = locked_assets[0]
            rental = Rental.objects.create(
                party=data["party"],
                product_label=f"{len(lines)} rental device{'s' if len(lines) != 1 else ''}: {first_asset.brand} {first_asset.model_name}",
                monthly_fee=sum(rates_by_asset_id.values()),
                start=data["start"],
                tenure_months=data["tenure_months"],
                last_payment=data["start"],
                terms=data.get("terms", ""),
            )
            rental.agreement_code = f"RNT-{rental.pk:06d}"
            rental.save(update_fields=["agreement_code"])
            RentalLine.objects.bulk_create([
                RentalLine(rental=rental, asset=asset, monthly_fee=rates_by_asset_id[asset.pk])
                for asset in locked_assets
            ])
            RentalAsset.objects.filter(pk__in=asset_ids).update(status=RentalAsset.RESERVED)
            RentalEvent.objects.create(
                rental=rental,
                event_type=RentalEvent.AGREEMENT_CREATED,
                actor=request.user,
                metadata={"rental_type": "bulk" if len(lines) >= 2 else "single", "line_count": len(lines)},
            )
        return Response(RentalSerializer(self._fresh(rental)).data, status=201)

    def _fresh(self, rental):
        return self.get_queryset().get(pk=rental.pk)

    @action(detail=True, methods=["post"], url_path="approval-link")
    def approval_link(self, request, pk=None):
        _, approval_url = issue_approval_link(self.get_object(), request.user)
        return Response({"approval_url": approval_url, "expires_in_hours": 24})

    @action(detail=True, methods=["post"], url_path="approve-on-behalf")
    def approve_on_behalf(self, request, pk=None):
        payload = StaffRentalApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approve_on_behalf(self.get_object(), request.user, payload.validated_data["reason"])
        return Response(RentalSerializer(self._fresh(self.get_object())).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        payload = StaffRentalApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        rental = cancel_agreement(self.get_object(), request.user, payload.validated_data["reason"])
        return Response(RentalSerializer(self._fresh(rental)).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        payload = StaffRentalApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        rental = close_agreement(self.get_object(), request.user, payload.validated_data["reason"])
        return Response(RentalSerializer(self._fresh(rental)).data)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail="Rental agreements are retained for audit. Cancel the agreement instead.")


class RentalAssetViewSet(viewsets.ModelViewSet):
    queryset = RentalAsset.objects.all()
    serializer_class = RentalAssetSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "rentals.view", "retrieve": "rentals.view",
        "create": "rentals.manage", "update": "rentals.manage",
        "partial_update": "rentals.manage", "destroy": "rentals.manage",
    }

    def perform_update(self, serializer):
        asset = self.get_object()
        if asset.status != RentalAsset.AVAILABLE:
            raise ValidationError({"detail": "An asset in use cannot be edited. Close or cancel its agreement first."})
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        asset = self.get_object()
        if asset.rental_lines.exists():
            raise ValidationError({"detail": "This asset has rental history and must be retired instead of deleted."})
        return super().destroy(request, *args, **kwargs)


class RentalApprovalPublicView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "rental_approval"

    @staticmethod
    def _private_response(data, status_code=status.HTTP_200_OK):
        response = Response(data, status=status_code)
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        response["Referrer-Policy"] = "no-referrer"
        return response

    def get(self, request, token):
        from .services import get_public_approval
        return self._private_response(PublicRentalApprovalSerializer(get_public_approval(token)).data)

    def post(self, request, token):
        payload = PublicRentalApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval = customer_decide(
            token,
            payload.validated_data["decision"],
            payload.validated_data.get("consent", False),
            payload.validated_data.get("reason", ""),
        )
        return self._private_response(PublicRentalApprovalSerializer(approval).data)


class RentalIssueViewSet(viewsets.ModelViewSet):
    """
    A client's complaint about their rented equipment. Any authenticated
    staff member can raise one on the client's behalf; assigning and
    resolving requires 'rentals.manage'. Resolving it happens by
    chatting with the client directly -- see parties.Message /
    POST /api/parties/{id}/message/ for the WhatsApp side of that.
    """
    queryset = RentalIssue.objects.select_related("rental__party", "assigned_to").all()
    serializer_class = RentalIssueSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "create": None,
        "update": "rentals.manage", "partial_update": "rentals.manage",
        "destroy": "rentals.manage", "assign": "rentals.manage", "resolve": "rentals.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        rental_id = self.request.query_params.get("rental")
        status_ = self.request.query_params.get("status")
        if rental_id:
            qs = qs.filter(rental_id=rental_id)
        if status_:
            qs = qs.filter(status=status_)
        return qs

    def perform_create(self, serializer):
        issue = serializer.save()
        # a raised issue is a real support touchpoint -- factor it into churn scoring
        Rental.objects.filter(pk=issue.rental_id).update(tickets=F("tickets") + 1)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        issue = self.get_object()
        user_id = request.data.get("assigned_to")
        issue.assigned_to_id = user_id
        if issue.status == RentalIssue.OPEN:
            issue.status = RentalIssue.IN_PROGRESS
        issue.save(update_fields=["assigned_to", "status"])
        return Response(RentalIssueSerializer(issue).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        issue = self.get_object()
        issue.status = RentalIssue.RESOLVED
        issue.resolved_at = timezone.now()
        issue.save(update_fields=["status", "resolved_at"])
        return Response(RentalIssueSerializer(issue).data)
