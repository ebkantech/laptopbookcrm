from datetime import date

from rest_framework import serializers

from catalog.models import Service, StockPoint, Variant
from catalog.serializers import ServiceSerializer
from catalog.status import require_active
from parties.models import Party
from sales.models import Invoice
from .models import (
    DEFAULT_APPROVAL_TERMS,
    Notification,
    RepairApproval,
    RepairEstimate,
    RepairEstimateLine,
    RepairOrder,
    RepairOrderApproval,
    RepairReopen,
    RepairReopenItem,
    RepairRevision,
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
    # staff-only: what the parts on this line cost the shop (for the profit
    # report). Never shown to the customer; blank = labour only.
    unit_cost = serializers.IntegerField(min_value=0, max_value=100_000_000, required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("unit_price") is None and not attrs.get("service"):
            raise serializers.ValidationError("Choose a service or enter a unit price.")
        return attrs


class PartInputSerializer(serializers.Serializer):
    """An inventory unit fitted to a new ticket: its product variant and exact serial number."""
    variant = serializers.PrimaryKeyRelatedField(queryset=Variant.objects.select_related("product"))
    serial_number = serializers.CharField(max_length=80, trim_whitespace=True)


class FinalizeEstimateSerializer(serializers.Serializer):
    lines = EstimateLineInputSerializer(many=True, allow_empty=False)
    terms = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RevisionLineInputSerializer(EstimateLineInputSerializer):
    pass


class ProposeRevisionSerializer(serializers.Serializer):
    lines = RevisionLineInputSerializer(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=1000, allow_blank=False, trim_whitespace=True)


class DiagnoseSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)
    estimate_ok = serializers.BooleanField(default=True)
    lines = EstimateLineInputSerializer(many=True, required=False)


class DecideRevisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "decline"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class RepairRevisionSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairRevision
        fields = ["id", "status", "reason", "lines", "proposed_total", "previous_total", "requested_by_name",
                  "decided_by_name", "decision_note", "created_at", "decided_at"]

    def get_requested_by_name(self, obj):
        return (obj.requested_by.get_full_name() or obj.requested_by.username) if obj.requested_by_id else ""

    def get_decided_by_name(self, obj):
        return (obj.decided_by.get_full_name() or obj.decided_by.username) if obj.decided_by_id else ""


class StaffApprovalSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)


class PublicApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject", "request_changes"])
    consent = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class RepairOrderDeviceInputSerializer(serializers.Serializer):
    brand = serializers.CharField(max_length=40, allow_blank=False, trim_whitespace=True)
    model_name = serializers.CharField(max_length=80, allow_blank=False, trim_whitespace=True)
    serial = serializers.CharField(max_length=60, allow_blank=False, trim_whitespace=True)
    issue = serializers.CharField(allow_blank=False, trim_whitespace=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source="services", queryset=Service.objects.all(), many=True, allow_empty=True, required=False, default=list
    )
    # Prices are agreed with the customer at the counter, so they're typed in
    # (not mapped from the catalogue), and so is the advance.
    estimate_lines = EstimateLineInputSerializer(many=True, required=False, default=list)
    parts = PartInputSerializer(many=True, required=False, default=list)
    advance_amount = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class CreateRepairOrderSerializer(serializers.Serializer):
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all())
    stock_point = serializers.PrimaryKeyRelatedField(queryset=StockPoint.objects.all())
    received = serializers.DateField()
    expected = serializers.DateField(required=False, allow_null=True)
    payment = serializers.ChoiceField(choices=RepairTicket.PAYMENT_CHOICES, default=RepairTicket.ADVANCE)
    devices = RepairOrderDeviceInputSerializer(many=True, allow_empty=False)

    def validate_stock_point(self, value):
        require_active(value, "repair orders")
        return value

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
    """A repair job's invoice (a sales.Invoice, source=repair) as the
    Repairs screen shows it; payment itself happens in Sales & Invoices."""
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    amount = serializers.IntegerField(source="total", read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "code", "amount", "stock_point", "stock_point_name", "status", "date", "paid_on", "pay_method"]


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


class StaffRepairEstimateLineSerializer(RepairEstimateLineSerializer):
    """Adds our parts cost -- staff screens only; the public approval page uses the base serializer."""

    class Meta(RepairEstimateLineSerializer.Meta):
        fields = RepairEstimateLineSerializer.Meta.fields + ["unit_cost"]


class RepairApprovalSummarySerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="effective_status", read_only=True)
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairApproval
        fields = ["id", "status", "source", "sent_to_phone", "created_at", "expires_at", "decided_at", "decided_by_name", "reason"]

    def get_decided_by_name(self, obj):
        return str(obj.decided_by) if obj.decided_by else ""


class RepairEstimateSerializer(serializers.ModelSerializer):
    lines = StaffRepairEstimateLineSerializer(many=True, read_only=True)
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
            "change_request": approval.reason if approval.status == RepairApproval.CHANGES_REQUESTED else "",
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
    pending_invoice = serializers.SerializerMethodField()
    advance_invoice = serializers.SerializerMethodField()
    current_estimate = serializers.SerializerMethodField()
    approval_status = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    order_code = serializers.CharField(source="order.code", read_only=True)
    repair_type = serializers.SerializerMethodField()
    order_id = serializers.IntegerField(read_only=True)
    order_device_count = serializers.SerializerMethodField()
    order_progress = serializers.SerializerMethodField()
    combined_approval_ready = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_store = serializers.SerializerMethodField()
    estimate_lines = EstimateLineInputSerializer(many=True, write_only=True, required=False)
    # inventory units fitted at booking (create only; see repairs.parts)
    parts = PartInputSerializer(many=True, write_only=True, required=False)
    parts_used = serializers.SerializerMethodField()
    advance_amount = serializers.IntegerField(min_value=0, write_only=True, required=False, allow_null=True)
    pending_revision = serializers.SerializerMethodField()
    revisions = RepairRevisionSerializer(many=True, read_only=True)
    on_hold_reason = serializers.CharField(read_only=True)
    due_at = serializers.SerializerMethodField()
    awaiting_diagnosis = serializers.BooleanField(read_only=True)
    diagnosed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = [
            "id", "code", "party", "party_name", "brand", "model_name", "serial",
            "stock_point", "stock_point_name", "issue", "services", "service_ids",
            "status", "received", "expected", "payment", "advance_paid",
            "notifications", "invoice", "reopens", "total", "balance_due",
            "warranty_active", "warranty_end_date", "can_reopen", "pending_invoice", "advance_invoice", "current_estimate",
            "approval_status", "events",
            "order_id", "order_code", "repair_type", "order_device_count",
            "order_progress", "combined_approval_ready", "assigned_to", "assigned_to_name", "assigned_to_store",
            "estimate_lines", "parts", "parts_used", "advance_amount", "assigned_at", "started_at", "ready_at", "due_at", "pending_revision", "revisions", "on_hold_reason",
            "diagnosed_at", "diagnosis_note", "diagnosed_by_name", "awaiting_diagnosis",
        ]
        # advance_paid only changes when the advance invoice is paid or refunded;
        # assignment only goes through the assign action
        read_only_fields = ["code", "status", "advance_paid", "assigned_to", "assigned_at", "started_at", "ready_at", "diagnosed_at", "diagnosis_note"]

    def get_pending_revision(self, obj):
        revision = obj.pending_revision
        return RepairRevisionSerializer(revision).data if revision else None

    def get_diagnosed_by_name(self, obj):
        return (obj.diagnosed_by.get_full_name() or obj.diagnosed_by.username) if obj.diagnosed_by_id else ""

    def get_due_at(self, obj):
        return obj.due_at

    def get_assigned_to_name(self, obj):
        return (obj.assigned_to.get_full_name() or obj.assigned_to.username) if obj.assigned_to_id else ""

    def get_assigned_to_store(self, obj):
        return obj.assigned_to.stock_point.name if obj.assigned_to_id and obj.assigned_to.stock_point_id else ""

    def validate_stock_point(self, value):
        # no new drop-off at an inactive shop; an existing ticket keeps its
        # shop (and stays fully workable) whatever that shop's status
        require_active(value, "repair tickets", current=self.instance.stock_point_id if self.instance else None)
        return value

    def get_parts_used(self, obj):
        return [{"id": u.id, "description": u.description, "serial_number": u.serial.serial_number, "variant": u.variant_id}
                for u in obj.part_uses.all()]

    def validate(self, attrs):
        if self.instance is not None and attrs.get("parts"):
            # fitted parts have left stock and there is no reversal rule, so they are set once, at booking
            raise serializers.ValidationError({"parts": "Parts are issued when the ticket is created and can't be changed afterwards."})
        lines = attrs.get("estimate_lines") or []
        amount = attrs.get("advance_amount")
        if amount is not None and lines and amount > sum(l["quantity"] * (l.get("unit_price") or 0) for l in lines):
            raise serializers.ValidationError({"advance_amount": "The advance can't be more than the estimate total."})
        if self.instance is None:
            serial = (attrs.get("serial") or "").strip()
            if not serial or serial == "—":
                raise serializers.ValidationError({"serial": "Serial number or asset tag is required."})
        return attrs

    def get_pending_invoice(self, obj):
        # raised but not yet paid -- the ticket waits at Ready for pickup
        inv = obj.unpaid_invoice
        return RepairInvoiceSerializer(inv).data if inv else None

    def get_advance_invoice(self, obj):
        inv = obj.advance_invoice
        return RepairInvoiceSerializer(inv).data if inv else None

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

    def get_events(self, obj):
        """
        The ticket's timeline. Whoever assigns jobs (repairs.assign, Admins,
        the Owner) sees all of it; once a ticket has been reassigned, the
        technician sees it being booked and everything from the current
        assignment on -- not who had it before or what happened then.
        """
        events = list(obj.events.all())
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not _sees_full_timeline(user):
            assigned = [i for i, e in enumerate(events) if e.event_type == RepairTicketEvent.ASSIGNED]
            if len(assigned) > 1:
                start = assigned[-1]
                events = [e for i, e in enumerate(events) if i >= start or e.event_type == RepairTicketEvent.TICKET_CREATED]
                data = RepairTicketEventSerializer(events, many=True).data
                for row in data:  # nor who it was taken from
                    if row["event_type"] == RepairTicketEvent.ASSIGNED and isinstance(row.get("metadata"), dict):
                        row["metadata"] = {k: v for k, v in row["metadata"].items() if k != "from"}
                return data
        return RepairTicketEventSerializer(events, many=True).data

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


def _sees_full_timeline(user):
    from accounts.staff import is_staff_admin

    return user.is_superuser or is_staff_admin(user) or user.has_perm_code("repairs.assign")
