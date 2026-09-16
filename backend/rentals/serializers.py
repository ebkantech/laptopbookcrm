from rest_framework import serializers

from parties.models import Party

from .models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalIssue, RentalLine


class RentalIssueSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    party_id = serializers.IntegerField(source="rental.party_id", read_only=True)
    party_name = serializers.CharField(source="rental.party.name", read_only=True)

    class Meta:
        model = RentalIssue
        fields = [
            "id", "rental", "title", "description", "status",
            "assigned_to", "assigned_to_name", "raised_at", "resolved_at",
            "party_id", "party_name",
        ]
        read_only_fields = ["status", "raised_at", "resolved_at"]

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to:
            return None
        return obj.assigned_to.get_full_name() or obj.assigned_to.username


class RentalSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    churn_score = serializers.IntegerField(read_only=True)
    churn_band = serializers.CharField(read_only=True)
    next_payment_date = serializers.DateField(read_only=True)
    next_payment_overdue = serializers.BooleanField(read_only=True)
    issues = RentalIssueSerializer(many=True, read_only=True)
    open_issue_count = serializers.SerializerMethodField()
    rental_type = serializers.CharField(read_only=True)
    total_monthly_fee = serializers.IntegerField(read_only=True)
    lines = serializers.SerializerMethodField()
    approval_status = serializers.SerializerMethodField()

    class Meta:
        model = Rental
        fields = [
            "id", "party", "party_name", "product_label", "monthly_fee", "start",
            "tenure_months", "months_paid", "late_count", "tickets", "last_payment",
            "agreement_code", "status", "terms", "rental_type", "total_monthly_fee", "lines", "approval_status",
            "next_payment_date", "next_payment_overdue",
            "churn_score", "churn_band", "issues", "open_issue_count",
        ]
        read_only_fields = ["agreement_code", "status"]

    def get_open_issue_count(self, obj):
        return sum(1 for i in obj.issues.all() if i.status != RentalIssue.RESOLVED)

    def get_lines(self, obj):
        return RentalLineSerializer(obj.lines.all(), many=True).data

    def get_approval_status(self, obj):
        approval = obj.approvals.order_by("-version").first()
        return approval.effective_status if approval else "not_sent"


class RentalAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalAsset
        fields = ["id", "asset_tag", "serial_number", "brand", "model_name", "status", "created_at"]
        # Availability is a workflow state. It can only change when an
        # agreement is approved, rejected, cancelled, or closed.
        read_only_fields = ["status", "created_at"]


class RentalLineSerializer(serializers.ModelSerializer):
    asset = RentalAssetSerializer(read_only=True)
    asset_id = serializers.IntegerField(source="asset.id", read_only=True)
    description = serializers.CharField(read_only=True)

    class Meta:
        model = RentalLine
        fields = ["id", "asset", "asset_id", "description", "monthly_fee"]


class CreateRentalLineSerializer(serializers.Serializer):
    asset_id = serializers.PrimaryKeyRelatedField(source="asset", queryset=RentalAsset.objects.all())
    monthly_fee = serializers.IntegerField(min_value=0)


class CreateRentalAgreementSerializer(serializers.Serializer):
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all())
    start = serializers.DateField()
    tenure_months = serializers.IntegerField(min_value=1)
    terms = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    lines = CreateRentalLineSerializer(many=True, allow_empty=False)

    def validate_lines(self, lines):
        asset_ids = [line["asset"].id for line in lines]
        if len(asset_ids) != len(set(asset_ids)):
            raise serializers.ValidationError("The same asset cannot be added twice to one rental agreement.")
        unavailable = [line["asset"].asset_tag for line in lines if line["asset"].status != RentalAsset.AVAILABLE]
        if unavailable:
            raise serializers.ValidationError(f"Assets must be Available before renting: {', '.join(unavailable)}.")
        return lines


class StaffRentalApprovalSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)


class PublicRentalApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    consent = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PublicRentalApprovalSerializer(serializers.Serializer):
    def to_representation(self, approval):
        snapshot = approval.snapshot
        customer = snapshot.get("customer") or {}
        return {
            "status": approval.effective_status,
            "source": approval.source,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            "version": approval.version,
            "agreement_code": snapshot.get("agreement_code"),
            "customer": {
                "name": customer.get("name"),
                "classification": customer.get("classification"),
            },
            "start": snapshot.get("start"),
            "tenure_months": snapshot.get("tenure_months"),
            "currency": snapshot.get("currency", "INR"),
            "terms": snapshot.get("terms", ""),
            "rental_type": snapshot.get("rental_type"),
            "items": snapshot.get("items", []),
            "total_monthly_fee": snapshot.get("total_monthly_fee", 0),
        }
