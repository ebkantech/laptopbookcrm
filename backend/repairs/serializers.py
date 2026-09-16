from datetime import date

from rest_framework import serializers

from catalog.models import Service, StockPoint
from catalog.serializers import ServiceSerializer
from parties.models import Party
from .models import (
    DEFAULT_APPROVAL_TERMS,
    Notification,
    RepairApproval,
    RepairEstimate,
    RepairEstimateLine,
    RepairInvoice,
    RepairOrder,
    RepairOrderApproval,
    RepairReopen,
    RepairReopenItem,
    RepairTicket,
    RepairTicketEvent,
)


class EstimateLineInputSerializer(serializers.Serializer):
    service_id = serializers.PrimaryKeyRelatedField(
        source="service", queryset=Service.objects.all(), required=False, allow_null=True
    )
    description = serializers.CharField(max_length=160, allow_blank=False, trim_whitespace=True)
    quantity = serializers.IntegerField(min_value=1, default=1)
    unit_price = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        if attrs.get("unit_price") is None and not attrs.get("service"):
            raise serializers.ValidationError("Choose a service or enter a unit price.")
        return attrs


class FinalizeEstimateSerializer(serializers.Serializer):
    lines = EstimateLineInputSerializer(many=True, allow_empty=False)
    terms = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class StaffApprovalSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)


class PublicApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    consent = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class RepairOrderDeviceInputSerializer(serializers.Serializer):
    brand = serializers.CharField(max_length=40, allow_blank=False, trim_whitespace=True)
    model_name = serializers.CharField(max_length=80, allow_blank=False, trim_whitespace=True)
    serial = serializers.CharField(max_length=60, allow_blank=False, trim_whitespace=True)
    issue = serializers.CharField(allow_blank=False, trim_whitespace=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source="services", queryset=Service.objects.all(), many=True, allow_empty=False
    )


class CreateRepairOrderSerializer(serializers.Serializer):
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all())
    stock_point = serializers.PrimaryKeyRelatedField(queryset=StockPoint.objects.all())
    received = serializers.DateField()
    expected = serializers.DateField(required=False, allow_null=True)
    payment = serializers.ChoiceField(choices=RepairTicket.PAYMENT_CHOICES, default=RepairTicket.ADVANCE)
    devices = RepairOrderDeviceInputSerializer(many=True, allow_empty=False)

    def validate_devices(self, devices):
        serials = [device["serial"].casefold() for device in devices]
        if len(serials) != len(set(serials)):
            raise serializers.ValidationError("Each physical device needs a different serial or asset tag.")
        return devices


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


class RepairEstimateLineSerializer(serializers.ModelSerializer):
    service_id = serializers.IntegerField(read_only=True)
    line_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = RepairEstimateLine
        fields = ["id", "service_id", "description", "quantity", "unit_price", "line_total"]


class RepairApprovalSummarySerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="effective_status", read_only=True)
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairApproval
        fields = ["id", "status", "source", "sent_to_phone", "created_at", "expires_at", "decided_at", "decided_by_name", "reason"]

    def get_decided_by_name(self, obj):
        return str(obj.decided_by) if obj.decided_by else ""


class RepairEstimateSerializer(serializers.ModelSerializer):
    lines = RepairEstimateLineSerializer(many=True, read_only=True)
    approval_status = serializers.CharField(read_only=True)
    approval = serializers.SerializerMethodField()
    balance_due = serializers.IntegerField(read_only=True)

    class Meta:
        model = RepairEstimate
        fields = ["id", "version", "is_current", "currency", "total_amount", "advance_paid", "balance_due", "terms", "created_at", "approval_status", "approval", "lines"]

    def get_approval(self, obj):
        approval = obj.latest_approval
        return RepairApprovalSummarySerializer(approval).data if approval else None


class RepairTicketEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicketEvent
        fields = ["id", "event_type", "metadata", "at", "actor_name"]

    def get_actor_name(self, obj):
        return str(obj.actor) if obj.actor else "Customer"


class PublicRepairApprovalSerializer(serializers.Serializer):
    def to_representation(self, approval):
        estimate = approval.estimate
        decided_at = approval.decided_at.isoformat() if approval.decided_at else None
        return {
            "status": approval.effective_status,
            "source": approval.source,
            "decided_at": decided_at,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            "ticket_code": estimate.ticket.code,
            "customer_name": estimate.customer_name,
            "device": {"brand": estimate.device_brand, "model_name": estimate.device_model, "serial": estimate.device_serial},
            "reported_issue": estimate.reported_issue,
            "estimate_version": estimate.version,
            "lines": RepairEstimateLineSerializer(estimate.lines.all(), many=True).data,
            "total_amount": estimate.total_amount,
            "advance_paid": estimate.advance_paid,
            "balance_due": estimate.balance_due,
            "currency": estimate.currency,
            "terms": estimate.terms,
        }


class PublicRepairOrderApprovalSerializer(serializers.Serializer):
    def to_representation(self, approval):
        snapshot = approval.snapshot
        return {
            "status": approval.effective_status,
            "source": approval.source,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            "version": approval.version,
            "order_code": snapshot.get("order_code"),
            "customer": snapshot.get("customer", {}),
            "repair_type": snapshot.get("repair_type"),
            "devices": snapshot.get("devices", []),
            "currency": snapshot.get("currency", "INR"),
            "grand_total": snapshot.get("grand_total", 0),
            "terms": snapshot.get("terms", DEFAULT_APPROVAL_TERMS),
        }


class RepairTicketSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    services = ServiceSerializer(many=True, read_only=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source="services", queryset=Service.objects.all(), many=True, write_only=True, required=False
    )
    notifications = NotificationSerializer(many=True, read_only=True)
    invoice = serializers.SerializerMethodField()
    reopens = RepairReopenSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    balance_due = serializers.IntegerField(read_only=True)
    warranty_active = serializers.SerializerMethodField()
    warranty_end_date = serializers.SerializerMethodField()
    can_reopen = serializers.SerializerMethodField()
    current_estimate = serializers.SerializerMethodField()
    approval_status = serializers.SerializerMethodField()
    events = RepairTicketEventSerializer(many=True, read_only=True)
    order_code = serializers.CharField(source="order.code", read_only=True)
    repair_type = serializers.SerializerMethodField()
    order_id = serializers.IntegerField(read_only=True)
    order_device_count = serializers.SerializerMethodField()
    order_progress = serializers.SerializerMethodField()
    combined_approval_ready = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = [
            "id", "code", "party", "party_name", "brand", "model_name", "serial",
            "stock_point", "stock_point_name", "issue", "services", "service_ids",
            "status", "received", "expected", "payment", "advance_paid",
            "notifications", "invoice", "reopens", "total", "balance_due",
            "warranty_active", "warranty_end_date", "can_reopen", "current_estimate",
            "approval_status", "events",
            "order_id", "order_code", "repair_type", "order_device_count",
            "order_progress", "combined_approval_ready",
        ]
        read_only_fields = ["code", "status"]

    def validate(self, attrs):
        if self.instance is None:
            serial = (attrs.get("serial") or "").strip()
            if not serial or serial == "—":
                raise serializers.ValidationError({"serial": "Serial number or asset tag is required."})
        return attrs

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

    def get_current_estimate(self, obj):
        estimate = obj.current_estimate
        return RepairEstimateSerializer(estimate).data if estimate else None

    def get_approval_status(self, obj):
        estimate = obj.current_estimate
        return estimate.approval_status if estimate else "not_sent"

    def get_repair_type(self, obj):
        return obj.order.repair_type if obj.order_id else "single"

    def get_order_device_count(self, obj):
        return obj.order.tickets.count() if obj.order_id else 1

    def get_order_progress(self, obj):
        if not obj.order_id:
            return []
        return [
            {
                "id": sibling.id,
                "code": sibling.code,
                "device": " ".join(part for part in [sibling.brand, sibling.model_name] if part).strip(),
                "serial": sibling.serial,
                "estimate_finalized": sibling.current_estimate is not None,
                "approval_status": sibling.current_estimate.approval_status if sibling.current_estimate else "not_sent",
            }
            for sibling in obj.order.tickets.all()
        ]

    def get_combined_approval_ready(self, obj):
        if not obj.order_id:
            return False
        progress = self.get_order_progress(obj)
        return len(progress) >= 2 and all(item["estimate_finalized"] for item in progress)


class RepairOrderSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    repair_type = serializers.CharField(read_only=True)
    tickets = RepairTicketSerializer(many=True, read_only=True)
    approval_status = serializers.SerializerMethodField()
    ready_for_approval = serializers.SerializerMethodField()

    class Meta:
        model = RepairOrder
        fields = [
            "id", "code", "party", "party_name", "repair_type", "created_at",
            "tickets", "approval_status", "ready_for_approval",
        ]

    def get_approval_status(self, obj):
        approval = obj.approvals.order_by("-version").first()
        return approval.effective_status if approval else "not_sent"

    def get_ready_for_approval(self, obj):
        tickets = list(obj.tickets.all())
        return len(tickets) >= 2 and all(ticket.current_estimate for ticket in tickets)


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
