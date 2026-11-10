from rest_framework import serializers

from .models import BankAccount, BankEntry, CashEntry


def _posted_from(entry):
    """The record an automatic entry mirrors: an invoice payment, a refund on
    one, or an expense payment (or its reversal)."""
    if entry.invoice_id:
        return entry.invoice.code
    if entry.refund_id:
        return entry.refund.invoice.code
    payment = entry.expense_payment or entry.expense_reversal
    if payment:
        return payment.expense.code
    if entry.invoice_payment_id:
        return entry.invoice_payment.invoice.code
    if entry.supplier_payment_id:
        return f"Supplier: {entry.supplier_payment.supplier.name}"
    if entry.staff_advance_id:
        staff = entry.staff_advance.staff
        return f"Staff advance: {staff.get_full_name() or staff.username}"
    return None


class CashEntrySerializer(serializers.ModelSerializer):
    by_name = serializers.CharField(source="by.get_full_name", read_only=True)
    invoice_code = serializers.SerializerMethodField()

    class Meta:
        model = CashEntry
        fields = ["id", "date", "particulars", "type", "amount", "by", "by_name", "invoice", "invoice_code"]
        read_only_fields = ["by", "invoice"]

    def get_invoice_code(self, obj):
        return _posted_from(obj)


class BankEntrySerializer(serializers.ModelSerializer):
    invoice_code = serializers.SerializerMethodField()

    class Meta:
        model = BankEntry
        fields = ["id", "account", "date", "particulars", "type", "amount", "reconciled", "reference", "invoice", "invoice_code"]
        read_only_fields = ["invoice", "reconciled"]

    def get_invoice_code(self, obj):
        return _posted_from(obj)


class BankAccountSerializer(serializers.ModelSerializer):
    entries = BankEntrySerializer(many=True, read_only=True)
    balance = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = ["id", "name", "opening", "is_default", "entries", "balance"]

    def get_balance(self, obj):
        total = obj.opening
        for e in obj.entries.exclude(particulars="Opening balance"):
            total += e.amount if e.type == BankEntry.IN else -e.amount
        return total
