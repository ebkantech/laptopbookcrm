from django.db import transaction
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import HasPerm
from .models import BankAccount, BankEntry, CashEntry
from .serializers import BankAccountSerializer, BankEntrySerializer, CashEntrySerializer


class CashEntryViewSet(viewsets.ModelViewSet):
    queryset = CashEntry.objects.select_related("by", "invoice").all()
    serializer_class = CashEntrySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "cashbook.view", "retrieve": "cashbook.view",
        "create": "cashbook.edit", "update": "cashbook.edit",
        "partial_update": "cashbook.edit", "destroy": "cashbook.edit",
    }

    def perform_create(self, serializer):
        serializer.save(by=self.request.user)

    def perform_update(self, serializer):
        _refuse_if_posted(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        _refuse_if_posted(instance)
        instance.delete()


def _refuse_if_posted(entry):
    """Entries posted from an invoice payment mirror that invoice."""
    if entry.invoice_id:
        raise ValidationError({"detail": f"This entry was posted from invoice {entry.invoice.code} and can't be changed here."})


class BankAccountViewSet(viewsets.ModelViewSet):
    """Bank accounts: rename, set the opening balance, choose the default
    account invoice payments are posted to. No deleting -- entries hang off it."""
    queryset = BankAccount.objects.prefetch_related("entries__invoice").all().order_by("id")
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "bankbook.view", "retrieve": "bankbook.view",
        "create": "bankbook.edit", "partial_update": "bankbook.edit",
    }

    @transaction.atomic
    def perform_create(self, serializer):
        account = serializer.save()
        self._single_default(account)

    @transaction.atomic
    def perform_update(self, serializer):
        account = serializer.save()
        self._single_default(account)

    @staticmethod
    def _single_default(account):
        if account.is_default:
            BankAccount.objects.exclude(pk=account.pk).update(is_default=False)
        elif not BankAccount.objects.filter(is_default=True).exists():
            account.is_default = True
            account.save(update_fields=["is_default"])


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
        qs = super().get_queryset().select_related("invoice")
        account = self.request.query_params.get("account")
        if account:
            qs = qs.filter(account_id=account)
        return qs

    def perform_update(self, serializer):
        _refuse_if_posted(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        _refuse_if_posted(instance)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="toggle-reconciled")
    def toggle_reconciled(self, request, pk=None):
        entry = self.get_object()
        entry.reconciled = not entry.reconciled
        entry.save(update_fields=["reconciled"])
        return Response(BankEntrySerializer(entry).data)
