from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from rentals.models import Rental
from repairs.models import RepairTicket

from .utils import normalize_phone


class CustomerLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)

    def validate_phone(self, value):
        return normalize_phone(value)


class CustomerPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    confirm_password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        user = self.context.get("user")
        validate_password(attrs["password"], user=user)
        return attrs


class CustomerDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    consent = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        if attrs["decision"] == "approve" and attrs.get("consent") is not True:
            raise serializers.ValidationError({"consent": "Confirm that you reviewed the final details and charges."})
        return attrs


class PortalRentalSerializer(serializers.ModelSerializer):
    rental_type = serializers.CharField(read_only=True)
    total_monthly_fee = serializers.IntegerField(read_only=True)
    items = serializers.SerializerMethodField()
    issues = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()

    class Meta:
        model = Rental
        fields = [
            "id", "agreement_code", "rental_type", "status", "start", "tenure_months",
            "months_paid", "total_monthly_fee", "terms", "items", "issues", "approval",
        ]

    def get_items(self, obj):
        lines = list(obj.lines.all())
        if lines:
            return [
                {
                    "asset_tag": line.asset.asset_tag,
                    "serial_number": line.asset.serial_number,
                    "brand": line.asset.brand,
                    "model_name": line.asset.model_name,
                    "monthly_fee": line.monthly_fee,
                }
                for line in lines
            ]
        return [{"brand": "", "model_name": obj.product_label, "monthly_fee": obj.monthly_fee}]

    def get_issues(self, obj):
        return [
            {
                "id": issue.id,
                "title": issue.title,
                "description": issue.description,
                "status": issue.status,
                "raised_at": issue.raised_at,
                "resolved_at": issue.resolved_at,
            }
            for issue in obj.issues.all()
        ]

    def get_approval(self, obj):
        approval = next(iter(obj.approvals.all()), None)
        if not approval:
            return None
        return {
            "id": approval.id,
            "kind": "rental",
            "status": approval.effective_status,
            "source": approval.source,
            "version": approval.version,
            "expires_at": approval.expires_at,
            "decided_at": approval.decided_at,
            "snapshot": approval.snapshot,
        }


class PortalRepairTicketSerializer(serializers.ModelSerializer):
    repair_type = serializers.SerializerMethodField()
    estimate = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = [
            "id", "code", "repair_type", "brand", "model_name", "serial", "issue",
            "status", "received", "expected", "payment", "advance_paid", "estimate",
            "invoice", "timeline",
        ]

    def get_repair_type(self, obj):
        return obj.order.repair_type if obj.order_id else "single"

    def get_estimate(self, obj):
        estimate = obj.current_estimate
        if not estimate:
            return None
        approval = estimate.latest_approval
        # A bulk order has one combined decision. Its linked per-device
        # approvals are display records, not separate actions for customers.
        if approval and approval.order_approval_id:
            approval = None
        return {
            "id": estimate.id,
            "version": estimate.version,
            "currency": estimate.currency,
            "total_amount": estimate.total_amount,
            "advance_paid": estimate.advance_paid,
            "balance_due": estimate.balance_due,
            "terms": estimate.terms,
            "created_at": estimate.created_at,
            "lines": [
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                }
                for line in estimate.lines.all()
            ],
            "approval": (
                {
                    "id": approval.id,
                    "kind": "repair",
                    "status": approval.effective_status,
                    "source": approval.source,
                    "expires_at": approval.expires_at,
                    "decided_at": approval.decided_at,
                }
                if approval else None
            ),
        }

    def get_invoice(self, obj):
        invoice = obj.original_invoice
        if not invoice:
            return None
        return {
            "code": invoice.code,
            "amount": invoice.amount,
            "status": invoice.status,
            "date": invoice.date,
        }

    def get_timeline(self, obj):
        labels = {
            "ticket_created": "Device received",
            "estimate_finalized": "Estimate finalized",
            "approval_link_created": "Approval requested",
            "approval_decided": "Approval decision recorded",
            "stage_changed": "Repair status updated",
            "settled": "Invoice settled",
            "modified_after_approval": "Service details updated",
        }
        return [
            {"type": event.event_type, "label": labels.get(event.event_type, "Service updated"), "at": event.at}
            for event in obj.events.all()
        ]
