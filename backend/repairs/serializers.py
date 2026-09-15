from datetime import date

from rest_framework import serializers

from catalog.models import Service
from catalog.serializers import ServiceSerializer
from .models import Notification, RepairInvoice, RepairReopen, RepairReopenItem, RepairTicket


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "channel", "text", "at"]
        read_only_fields = ["at"]


class RepairInvoiceSerializer(serializers.ModelSerializer):
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)

    class Meta:
        model = RepairInvoice
        fields = ["id", "code", "amount", "stock_point", "stock_point_name", "status", "date"]


class RepairReopenItemSerializer(serializers.ModelSerializer):
    service_label = serializers.CharField(source="service.label", read_only=True)

    class Meta:
        model = RepairReopenItem
        fields = ["id", "service", "service_label", "charge", "covered_by_warranty"]


class RepairReopenSerializer(serializers.ModelSerializer):
    items = RepairReopenItemSerializer(many=True, read_only=True)
    invoice = RepairInvoiceSerializer(read_only=True)
    total = serializers.IntegerField(read_only=True)

    class Meta:
        model = RepairReopen
        fields = ["id", "ticket", "issue", "opened_at", "items", "invoice", "total"]


class RepairTicketSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    services = ServiceSerializer(many=True, read_only=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source="services", queryset=Service.objects.all(), many=True, write_only=True
    )
    notifications = NotificationSerializer(many=True, read_only=True)
    invoice = serializers.SerializerMethodField()
    reopens = RepairReopenSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    balance_due = serializers.IntegerField(read_only=True)
    warranty_active = serializers.SerializerMethodField()
    warranty_end_date = serializers.SerializerMethodField()
    can_reopen = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = [
            "id", "code", "party", "party_name", "brand", "model_name", "serial",
            "stock_point", "stock_point_name", "issue", "services", "service_ids",
            "status", "received", "expected", "payment", "advance_paid",
            "notifications", "invoice", "reopens", "total", "balance_due",
            "warranty_active", "warranty_end_date", "can_reopen",
        ]
        read_only_fields = ["code", "status"]

    def get_invoice(self, obj):
        # the ORIGINAL delivery's bill specifically -- a reopen's bill
        # lives on that reopen's own `invoice` field instead, so this
        # never gets overwritten/confused by a later visit's invoice
        inv = obj.original_invoice
        return RepairInvoiceSerializer(inv).data if inv else None

    def _active_warranty(self, obj):
        # local import -- avoids a circular import at module load time,
        # since warranty.models already imports RepairTicket the other way
        from warranty.models import Warranty
        return (
            Warranty.objects.filter(repair_ticket=obj, section=Warranty.REPAIR, end_date__gte=date.today())
            .order_by("-end_date")
            .first()
        )

    def get_warranty_active(self, obj):
        return self._active_warranty(obj) is not None

    def get_warranty_end_date(self, obj):
        w = self._active_warranty(obj)
        return w.end_date if w else None

    def get_can_reopen(self, obj):
        return obj.status == RepairTicket.DELIVERED and obj.active_reopen is None


class RepairInvoiceListSerializer(serializers.ModelSerializer):
    """
    Flat view of a repair bill for surfacing alongside Sales invoices --
    repair revenue was previously invisible outside the Repairs module
    entirely (a completely separate table from sales.Invoice), which is
    exactly the "invoice not updating" gap this closes.
    """
    party_name = serializers.CharField(source="ticket.party.name", read_only=True)
    ticket_code = serializers.CharField(source="ticket.code", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    is_followup = serializers.SerializerMethodField()

    class Meta:
        model = RepairInvoice
        fields = ["id", "code", "ticket", "ticket_code", "party_name", "amount", "stock_point", "stock_point_name", "status", "date", "is_followup"]

    def get_is_followup(self, obj):
        return obj.reopen_id is not None
