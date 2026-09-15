from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from .models import BankAccount, BankEntry, CashEntry
from .serializers import BankAccountSerializer, BankEntrySerializer, CashEntrySerializer


class CashEntryViewSet(viewsets.ModelViewSet):
    queryset = CashEntry.objects.select_related("by").all()
    serializer_class = CashEntrySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "cashbook.view", "retrieve": "cashbook.view",
        "create": "cashbook.edit", "update": "cashbook.edit",
        "partial_update": "cashbook.edit", "destroy": "cashbook.edit",
    }

    def perform_create(self, serializer):
        serializer.save(by=self.request.user)


class BankAccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BankAccount.objects.prefetch_related("entries").all()
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "bankbook.view"


class BankEntryViewSet(viewsets.ModelViewSet):
    queryset = BankEntry.objects.select_related("account").all()
    serializer_class = BankEntrySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "bankbook.view", "retrieve": "bankbook.view",
        "create": "bankbook.edit", "update": "bankbook.edit",
        "partial_update": "bankbook.edit", "destroy": "bankbook.edit",
        "toggle_reconciled": "bankbook.reconcile",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        account = self.request.query_params.get("account")
        if account:
            qs = qs.filter(account_id=account)
        return qs

    @action(detail=True, methods=["post"], url_path="toggle-reconciled")
    def toggle_reconciled(self, request, pk=None):
        entry = self.get_object()
        entry.reconciled = not entry.reconciled
        entry.save(update_fields=["reconciled"])
        return Response(BankEntrySerializer(entry).data)
