from rest_framework import serializers

from sales.models import Invoice
from .models import Message, Party


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "party", "channel", "direction", "body", "at"]
        read_only_fields = ["at"]


class PartyInvoiceSerializer(serializers.ModelSerializer):
    """Lightweight invoice view for the party detail popup -- no need to
    repeat the party's own name/id back to itself here."""
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "date", "status", "stock_point_name", "total",
            "item_count", "pay_method", "recurring_interval",
        ]

    def get_item_count(self, obj):
        return obj.items.count()


class PartySerializer(serializers.ModelSerializer):
    total_spent = serializers.SerializerMethodField()
    invoice_count = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = [
            "id", "name", "type", "phone", "email", "gstin", "city", "joined",
            "total_spent", "invoice_count",
        ]

    def get_total_spent(self, obj):
        return sum(inv.total for inv in obj.invoices.all())

    def get_invoice_count(self, obj):
        return obj.invoices.count()


class PartyDetailSerializer(PartySerializer):
    messages = MessageSerializer(many=True, read_only=True)
    invoices = PartyInvoiceSerializer(many=True, read_only=True)

    class Meta(PartySerializer.Meta):
        fields = PartySerializer.Meta.fields + ["messages", "invoices"]
