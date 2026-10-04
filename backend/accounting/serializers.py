from rest_framework import serializers

from .models import BankAccount, BankEntry, CashEntry


def _posted_from(entry):
    """The invoice an automatic entry mirrors: its payment, or a refund on it."""
    if entry.invoice_id:
        return entry.invoice.code
    if entry.refund_id:
        return entry.refund.invoice.code
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
