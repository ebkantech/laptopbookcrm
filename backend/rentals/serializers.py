from rest_framework import serializers

from catalog.models import Stock
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
    rent_invoices = serializers.SerializerMethodField()
    next_billing_period = serializers.SerializerMethodField()

    class Meta:
        model = Rental
        fields = [
            "id", "party", "party_name", "product_label", "monthly_fee", "start",
            "tenure_months", "months_paid", "late_count", "tickets", "last_payment",
            "agreement_code", "status", "terms", "rental_type", "total_monthly_fee", "lines", "approval_status",
            "next_payment_date", "next_payment_overdue",
            "churn_score", "churn_band", "issues", "open_issue_count",
            "rent_invoices", "next_billing_period",
        ]
        # Payment counters only move when a rent invoice is paid in Sales &
        # Invoices (rentals.billing.on_rent_invoice_paid) -- never by hand.
        read_only_fields = ["agreement_code", "status", "months_paid", "late_count", "last_payment"]

    def get_rent_invoices(self, obj):
        return [
            {
                "id": inv.id, "code": inv.code, "date": inv.date, "status": inv.status, "total": inv.total,
                "period_start": inv.period_start, "period_end": inv.period_end, "paid_on": inv.paid_on,
            }
            for inv in obj.invoices.all()
        ]

    def get_next_billing_period(self, obj):
        from .billing import next_billing_period

        period = next_billing_period(obj)
        return {"start": period[0], "end": period[1]} if period else None

    def get_open_issue_count(self, obj):
        return sum(1 for i in obj.issues.all() if i.status != RentalIssue.RESOLVED)

    def get_lines(self, obj):
        return RentalLineSerializer(obj.lines.all(), many=True).data

    def get_approval_status(self, obj):
        approval = obj.approvals.order_by("-version").first()
        return approval.effective_status if approval else "not_sent"


class RentalAssetSerializer(serializers.ModelSerializer):
    # Optional: left blank, the next AST-#### tag is generated on create.
    asset_tag = serializers.CharField(max_length=48, required=False, allow_blank=True)
    source_stock_point_name = serializers.CharField(source="source_stock_point.name", read_only=True, default=None)
    returned_to_name = serializers.CharField(source="returned_to.name", read_only=True, default=None)

    class Meta:
        model = RentalAsset
        fields = [
            "id", "asset_tag", "serial_number", "brand", "model_name", "status", "created_at", "variant",
            "source_stock_point", "source_stock_point_name", "returned_to_stock_at", "returned_to", "returned_to_name",
        ]
        # Availability is a workflow state. It can only change when an
        # agreement is approved, rejected, cancelled, or closed.
        read_only_fields = ["status", "created_at", "variant", "source_stock_point", "returned_to_stock_at", "returned_to"]
        # uniqueness is checked case-insensitively in validate() instead,
        # with a message that says where the existing asset is
        validators = []

    @staticmethod
    def _where(asset):
        line = asset.rental_lines.select_related("rental").order_by("-id").first()
        if asset.status == RentalAsset.AVAILABLE:
            return "it's available -- pick it from the device list instead of registering it again"
        if line and asset.status in (RentalAsset.RESERVED, RentalAsset.RENTED):
            return f"it's {asset.get_status_display().lower()} on agreement {line.rental.agreement_code or line.rental_id}"
        return f"its status is {asset.get_status_display().lower()}"

    def _duplicate(self, field, value, label):
        qs = RentalAsset.objects.filter(**{f"{field}__iexact": value})
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        existing = qs.first()
        if existing:
            raise serializers.ValidationError({
                field: f"{label} {existing.__getattribute__(field)} is already registered "
                       f"({existing.brand} {existing.model_name}) -- {self._where(existing)}.",
                "existing_asset": RentalAssetSerializer(existing).data,
            })

    def validate(self, attrs):
        for key in ("asset_tag", "serial_number", "brand", "model_name"):
            if key in attrs:
                attrs[key] = attrs[key].strip()
        tag = attrs.get("asset_tag")
        if tag and not any(ch.isdigit() for ch in tag):
            # "laptop", "dell"... -- a tag identifies one physical unit
            raise serializers.ValidationError({
                "asset_tag": (
                    f'"{tag}" is not an asset tag -- the tag is the unique ID on this unit\'s sticker '
                    "(e.g. AST-0042). Leave it blank to generate one."
                ),
            })
        if attrs.get("serial_number"):
            self._duplicate("serial_number", attrs["serial_number"], "Serial number")
        if attrs.get("asset_tag"):
            self._duplicate("asset_tag", attrs["asset_tag"], "Asset tag")
        elif self.instance is not None and "asset_tag" in attrs:
            raise serializers.ValidationError({"asset_tag": "An asset tag can't be blank."})
        return attrs

    def create(self, validated_data):
        if not validated_data.get("asset_tag"):
            from catalog.utils import next_code

            validated_data["asset_tag"] = next_code("AST", RentalAsset, "asset_tag")
        return super().create(validated_data)


class RentalLineSerializer(serializers.ModelSerializer):
    asset = RentalAssetSerializer(read_only=True)
    asset_id = serializers.IntegerField(source="asset.id", read_only=True)
    description = serializers.CharField(read_only=True)
    # summary only -- the full handover record is at /rental-lines/<id>/handover/
    handover_issues = serializers.SerializerMethodField()
    photo_count = serializers.SerializerMethodField()

    class Meta:
        model = RentalLine
        fields = [
            "id", "asset", "asset_id", "description", "monthly_fee",
            "handover_issues", "photo_count", "warranty_included", "warranty_months",
        ]

    def get_handover_issues(self, obj):
        return obj.handover_issues()

    def get_photo_count(self, obj):
        return len(obj.photos.all())


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


class AssetFromInventorySerializer(serializers.Serializer):
    """Take one unit off a shop's sale stock and register it for rent."""
    stock = serializers.PrimaryKeyRelatedField(queryset=Stock.objects.select_related("variant__product", "stock_point"))
    serial_number = serializers.CharField(max_length=80, trim_whitespace=True)
    asset_tag = serializers.CharField(max_length=48, required=False, allow_blank=True, trim_whitespace=True)
