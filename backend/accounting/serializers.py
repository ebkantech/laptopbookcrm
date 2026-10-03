from rest_framework import serializers

from .models import BankAccount, BankEntry, CashEntry


class CashEntrySerializer(serializers.ModelSerializer):
    by_name = serializers.CharField(source="by.get_full_name", read_only=True)
    invoice_code = serializers.CharField(source="invoice.code", read_only=True, default=None)

    class Meta:
        model = CashEntry
        fields = ["id", "date", "particulars", "type", "amount", "by", "by_name", "invoice", "invoice_code"]
        read_only_fields = ["by", "invoice"]


class BankEntrySerializer(serializers.ModelSerializer):
    invoice_code = serializers.CharField(source="invoice.code", read_only=True, default=None)

    class Meta:
        model = BankEntry
        fields = ["id", "account", "date", "particulars", "type", "amount", "reconciled", "reference", "invoice", "invoice_code"]
        read_only_fields = ["invoice", "reconciled"]


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
