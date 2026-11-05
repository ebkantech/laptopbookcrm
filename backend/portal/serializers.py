from rest_framework import serializers

from parties.models import Party
from rentals import onboarding
from rentals.models import Rental, RentalIssue
from repairs.models import RepairTicket
from sales.models import Invoice, PaymentLink
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
    repair_only = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = ["id", "name", "phone", "email", "city", "joined", "type", "portal_access_ends_at", "repair_only"]

    def get_repair_only(self, obj):
        return access.repair_only(obj)

    def get_type(self, obj):
        return access.account_type(obj)

    def get_portal_access_ends_at(self, obj):
        """When a Rental customer's portal access ends (exclusive); null for other account types."""
        if obj.type != Party.RENTAL:
            return None
        ends_at = access.rental_access_ends_at(obj)
        return serializers.DateTimeField().to_representation(ends_at) if ends_at else None


def payment_url(invoice):
    """The link staff sent for a bill that is still owed. Paid or cancelled bills never carry one."""
    if invoice.status not in Invoice.OUTSTANDING:
        return None
    for link in invoice.payment_links.all():  # newest first
        if link.status == PaymentLink.SENT and link.url.startswith("https://"):
            return link.url
    return None


class PortalInvoiceSerializer(serializers.ModelSerializer):
    """Customer-safe invoice fields only: no staff names, cancel reasons or refunds detail. The one
    payment field is the customer's own link to pay a bill still owed, never the link records."""
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    currency = serializers.SerializerMethodField()
    reference = serializers.SerializerMethodField()
    pdf_available = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    payment_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "reference", "date", "due_date", "paid_on", "status", "stock_point_name",
            "period_start", "period_end", "total", "currency", "pdf_available", "items", "payment_url",
        ]

    def get_payment_url(self, obj):
        return payment_url(obj)

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
    payment_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "code", "ticket_code", "amount", "status", "date", "payment_url"]

    def get_payment_url(self, obj):
        return payment_url(obj)


class PortalRepairTicketSerializer(serializers.ModelSerializer):
    services = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="stock_point.name", read_only=True)
    stages = serializers.SerializerMethodField()

    class Meta:
        model = RepairTicket
        fields = ["id", "code", "brand", "model_name", "issue", "status", "received", "expected", "services",
                  "store_name", "stages"]

    def get_stages(self, obj):
        """The steps a job passes through, in order, for the progress display."""
        return RepairTicket.STAGES

    def get_services(self, obj):
        return [s.label for s in obj.services.all()]


class PortalRentalSerializer(serializers.ModelSerializer):
    next_payment_date = serializers.DateField(read_only=True)
    next_payment_overdue = serializers.BooleanField(read_only=True)
    end_date = serializers.SerializerMethodField()
    total_monthly_fee = serializers.IntegerField(read_only=True)
    devices = serializers.SerializerMethodField()
    laptop_status = serializers.SerializerMethodField()
    security_deposit = serializers.SerializerMethodField()
    advance = serializers.SerializerMethodField()
    payments_due = serializers.SerializerMethodField()
    payment_history = serializers.SerializerMethodField()
    signed_agreement_uploaded_at = serializers.SerializerMethodField()

    class Meta:
        # deliberately NOT exposing churn_score/churn_band/late_count/tickets --
        # that's an internal risk signal for staff, not something to show the customer
        model = Rental
        fields = [
            "id", "agreement_code", "status", "product_label", "monthly_fee", "total_monthly_fee", "start",
            "tenure_months", "end_date", "months_paid", "next_payment_date", "next_payment_overdue", "devices",
            "laptop_status", "security_deposit", "advance", "payments_due", "payment_history",
            "signed_agreement_uploaded_at",
        ]

    def get_end_date(self, obj):
        """Last day the agreement covers (inclusive), same convention as rent billing."""
        return access.rental_last_day(obj).isoformat()

    def get_devices(self, obj):
        return [
            {"description": line.description, "serial_number": line.asset.serial_number, "monthly_fee": line.monthly_fee}
            for line in obj.lines.all()
        ]

    def get_laptop_status(self, obj):
        return onboarding.laptop_status(obj)

    @staticmethod
    def _held(invoice):
        """A deposit or advance as the customer sees it. Part refunds keep the invoice Paid."""
        if invoice is None:
            return None
        return {
            "code": invoice.code, "amount": invoice.total, "status": invoice.status, "paid_on": invoice.paid_on,
            "refunded": invoice.refunded_total, "payment_url": payment_url(invoice),
        }

    def get_security_deposit(self, obj):
        return self._held(onboarding.deposit_invoice(obj))

    def get_advance(self, obj):
        return self._held(onboarding.advance_invoice(obj))

    def get_signed_agreement_uploaded_at(self, obj):
        """When the signed copy went on file; null means the portal has nothing to offer."""
        if not obj.signed_agreement:
            return None
        return serializers.DateTimeField().to_representation(obj.signed_uploaded_at) if obj.signed_uploaded_at else None

    @staticmethod
    def _payment_label(invoice):
        if invoice.is_deposit:
            return "Security deposit"
        if invoice.is_advance:
            return "Advance rent"
        if invoice.period_start and invoice.period_end:
            return f"Rent {invoice.period_start:%d %b %Y} to {invoice.period_end:%d %b %Y}"
        return "Rent"

    def get_payment_history(self, obj):
        paid = obj.invoices.filter(status__in=Invoice.SETTLED).order_by("-paid_on", "-id")
        return [
            {"id": invoice.id, "code": invoice.code, "label": self._payment_label(invoice), "amount": invoice.total,
             "paid_on": invoice.paid_on, "pay_method": invoice.pay_method, "status": invoice.status,
             "refunded": invoice.refunded_total}
            for invoice in paid.prefetch_related("items", "refunds")
        ]

    def get_payments_due(self, obj):
        due = obj.invoices.filter(status__in=Invoice.OUTSTANDING).order_by("due_date", "id")
        return [
            {"id": invoice.id, "code": invoice.code, "amount": invoice.total, "due_date": invoice.due_date,
             "status": invoice.status, "payment_url": payment_url(invoice)}
            for invoice in due.prefetch_related("items", "payment_links")
        ]


class PortalIssueSerializer(serializers.ModelSerializer):
    """An issue as its customer sees it: never who it is assigned to."""
    agreement_code = serializers.CharField(source="rental.agreement_code", read_only=True)

    class Meta:
        model = RentalIssue
        fields = ["id", "rental", "agreement_code", "title", "description", "status", "raised_at", "resolved_at"]
        read_only_fields = fields


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
