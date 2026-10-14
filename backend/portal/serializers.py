from rest_framework import serializers

from parties.models import Party
from rentals.models import Rental
from repairs.models import RepairTicket
from sales.models import Invoice
from sales.documents import CURRENCY, pdf_available
from sales.serializers import InvoiceSerializer
from warranty.models import Warranty
from . import access
from .models import Feedback, PortalAccessLog, PortalInvite


class PortalPartySerializer(serializers.ModelSerializer):
    """
    The signed-in customer's own profile. `type` is the canonical
    Party.type ("Rental" | "Dealer" | "Retail", or "Unknown" for anything
    else) -- deliberately NOT customer_classification, which is an
    unrelated internal label (a Rental account can be classified "dealer").
    """
    type = serializers.SerializerMethodField()
    portal_access_ends_at = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = ["id", "name", "phone", "email", "city", "joined", "type", "portal_access_ends_at"]

    def get_type(self, obj):
        return access.account_type(obj)

    def get_portal_access_ends_at(self, obj):
        """When a Rental customer's portal access ends (exclusive); null for other account types."""
        if obj.type != Party.RENTAL:
            return None
        ends_at = access.rental_access_ends_at(obj)
        return serializers.DateTimeField().to_representation(ends_at) if ends_at else None


class PortalInvoiceSerializer(serializers.ModelSerializer):
    """Customer-safe invoice fields only: no staff names, cancel reasons, payment links or refunds detail."""
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    currency = serializers.SerializerMethodField()
    reference = serializers.SerializerMethodField()
    pdf_available = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "reference", "date", "due_date", "paid_on", "status", "stock_point_name",
            "period_start", "period_end", "total", "currency", "pdf_available", "items",
        ]

    def get_currency(self, obj):
        return CURRENCY

    def get_reference(self, obj):
        return InvoiceSerializer().get_reference(obj)

    def get_pdf_available(self, obj):
        return pdf_available(obj)

    def get_items(self, obj):
        return [
            {"product": i.label, "spec": i.variant.spec if i.variant_id else "", "qty": i.qty, "price": i.price,
             "amount": i.qty * i.price}
            for i in obj.items.all()
        ]


class PortalInvoiceDetailSerializer(PortalInvoiceSerializer):
    refunded_total = serializers.IntegerField(read_only=True)

    class Meta(PortalInvoiceSerializer.Meta):
        fields = PortalInvoiceSerializer.Meta.fields + ["pay_method", "payment_reference", "refunded_total"]


class PortalRepairInvoiceSerializer(serializers.ModelSerializer):
    ticket_code = serializers.CharField(source="repair_ticket.code", read_only=True)
    amount = serializers.IntegerField(source="total", read_only=True)

    class Meta:
        model = Invoice
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
    end_date = serializers.SerializerMethodField()
    total_monthly_fee = serializers.IntegerField(read_only=True)
    devices = serializers.SerializerMethodField()

    class Meta:
        # deliberately NOT exposing churn_score/churn_band/late_count/tickets --
        # that's an internal risk signal for staff, not something to show the customer
        model = Rental
        fields = [
            "id", "agreement_code", "status", "product_label", "monthly_fee", "total_monthly_fee", "start",
            "tenure_months", "end_date", "months_paid", "next_payment_date", "next_payment_overdue", "devices",
        ]

    def get_end_date(self, obj):
        """Last day the agreement covers (inclusive), same convention as rent billing."""
        return access.rental_last_day(obj).isoformat()

    def get_devices(self, obj):
        return [
            {"description": line.description, "serial_number": line.asset.serial_number, "monthly_fee": line.monthly_fee}
            for line in obj.lines.all()
        ]


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
