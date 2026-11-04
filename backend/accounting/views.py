from django.db import transaction
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope, StoreScopedMixin
from .models import BankAccount, BankEntry, CashEntry
from .serializers import BankAccountSerializer, BankEntrySerializer, CashEntrySerializer


# Cash and bank books are business-wide. The only reliable store link an
# entry has is the invoice (or refund's invoice) or the expense it was
# posted from, so store staff see those entries for their own store; manual
# entries, shared expenses and bank accounts (whose balances mix every
# store) are Owner-only.
LEDGER_STORE_LOOKUPS = (
    "invoice__stock_point", "refund__invoice__stock_point",
    "expense_payment__expense__stock_point", "expense_reversal__expense__stock_point",
)
MANUAL_ENTRY_DETAIL = "Manual cash and bank entries aren't tied to a store, so only the Owner can record them."


class CashEntryViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    store_lookups = LEDGER_STORE_LOOKUPS
    store_payload_field = None
    queryset = CashEntry.objects.select_related(
        "by", "invoice", "refund__invoice", "expense_payment__expense", "expense_reversal__expense",
    ).all()
    serializer_class = CashEntrySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "cashbook.view", "retrieve": "cashbook.view",
        "create": "cashbook.edit", "update": "cashbook.edit",
        "partial_update": "cashbook.edit", "destroy": "cashbook.edit",
    }

    def perform_create(self, serializer):
        self.store_scope.require_owner(MANUAL_ENTRY_DETAIL)
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
    if entry.refund_id:
        raise ValidationError({"detail": f"This entry is a refund on invoice {entry.refund.invoice.code} and can't be changed here."})
    payment = entry.expense_payment or entry.expense_reversal
    if payment is not None:
        raise ValidationError({"detail": f"This entry was posted from expense {payment.expense.code} and can't be changed here."})


class BankAccountViewSet(viewsets.ModelViewSet):
    """Bank accounts: rename, set the opening balance, choose the default
    account invoice payments are posted to. No deleting -- entries hang off it."""
    queryset = BankAccount.objects.prefetch_related("entries__invoice", "entries__refund__invoice").all().order_by("id")
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "bankbook.view", "retrieve": "bankbook.view",
        "create": "bankbook.edit", "partial_update": "bankbook.edit",
    }

    def get_queryset(self):
        # an account's balance and entries span every store -- Owner only,
        # whichever store the sidebar has in view
        qs = super().get_queryset()
        return qs if StoreScope(self.request.user).owner else qs.none()

    @transaction.atomic
    def perform_create(self, serializer):
        # Owner / Super Admin (the Owner role) or a superuser only -- an Admin
        # holding bankbook.edit still can't open an account
        StoreScope(self.request.user).require_owner("Bank accounts are business-wide -- only the Owner can add one.")
        # always a new row: an existing account is only ever changed by PATCH on its own id
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


class BankEntryViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    store_lookups = LEDGER_STORE_LOOKUPS
    store_payload_field = None
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
        qs = super().get_queryset().select_related("invoice", "refund__invoice", "expense_payment__expense", "expense_reversal__expense")
        account = self.request.query_params.get("account")
        if account:
            qs = qs.filter(account_id=account)
        return qs

    def perform_create(self, serializer):
        self.store_scope.require_owner(MANUAL_ENTRY_DETAIL)
        serializer.save()

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
