from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from .models import Rental, RentalIssue
from .serializers import RentalIssueSerializer, RentalSerializer


class RentalViewSet(viewsets.ModelViewSet):
    queryset = Rental.objects.select_related("party").prefetch_related("issues__assigned_to").all()
    serializer_class = RentalSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None,
        "create": "rentals.manage", "update": "rentals.manage",
        "partial_update": "rentals.manage", "destroy": "rentals.manage",
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
