from rest_framework import serializers

from .models import Rental, RentalIssue


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

    class Meta:
        model = Rental
        fields = [
            "id", "party", "party_name", "product_label", "monthly_fee", "start",
            "tenure_months", "months_paid", "late_count", "tickets", "last_payment",
            "next_payment_date", "next_payment_overdue",
            "churn_score", "churn_band", "issues", "open_issue_count",
        ]

    def get_open_issue_count(self, obj):
        return sum(1 for i in obj.issues.all() if i.status != RentalIssue.RESOLVED)
