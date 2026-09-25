from rest_framework import serializers

from parties.models import Party
from rentals.models import Rental
from repairs.models import RepairInvoice, RepairTicket
from sales.models import Invoice
from warranty.models import Warranty
from .models import Feedback, PortalAccessLog, PortalInvite


class PortalPartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "name", "phone", "email", "city", "joined"]


class PortalInvoiceSerializer(serializers.ModelSerializer):
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "code", "date", "status", "stock_point_name", "total", "items"]

    def get_items(self, obj):
        return [
            {"product": i.variant.product.display_name, "spec": i.variant.spec, "qty": i.qty, "price": i.price}
            for i in obj.items.all()
        ]


class PortalRepairInvoiceSerializer(serializers.ModelSerializer):
    ticket_code = serializers.CharField(source="ticket.code", read_only=True)

    class Meta:
        model = RepairInvoice
        fields = ["id", "code", "ticket_code", "amount", "status", "date"]


class PortalRepairTicketSerializer(serializers.ModelSerializer):
    services = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = ["id", "code", "brand", "model_name", "issue", "status", "received", "expected", "services"]

    def get_services(self, obj):
        return [s.label for s in obj.services.all()]


class PortalRentalSerializer(serializers.ModelSerializer):
    next_payment_date = serializers.DateField(read_only=True)
    next_payment_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        # deliberately NOT exposing churn_score/churn_band/late_count/tickets --
        # that's an internal risk signal for staff, not something to show the customer
        model = Rental
        fields = ["id", "product_label", "monthly_fee", "start", "tenure_months", "months_paid", "next_payment_date", "next_payment_overdue"]


class PortalWarrantySerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Warranty
        fields = ["id", "section", "item_label", "start_date", "end_date", "status"]


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ["id", "rating", "comment", "created_at"]
        read_only_fields = ["created_at"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class PortalInviteSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)

    class Meta:
        model = PortalInvite
        fields = ["id", "party", "party_name", "created_at", "expires_at"]
        read_only_fields = ["created_at", "expires_at"]


class PortalAccessLogSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    has_location = serializers.SerializerMethodField()

    class Meta:
        model = PortalAccessLog
        fields = ["id", "party", "party_name", "ip_address", "user_agent", "latitude", "longitude", "location_accuracy_m", "has_location", "created_at"]

    def get_has_location(self, obj):
        return obj.latitude is not None and obj.longitude is not None
