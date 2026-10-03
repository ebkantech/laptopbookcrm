from django.db import transaction
from django.db.models import F
from rest_framework import serializers

from catalog.models import Stock
from .models import Invoice, InvoiceItem, PaymentLink
from .services import create_invoice


class InvoiceItemSerializer(serializers.ModelSerializer):
    variant_code = serializers.SerializerMethodField()
    # Kept as product_name for existing callers: the line's label, i.e.
    # the product for a sale line or the service/rent description.
    product_name = serializers.CharField(source="label", read_only=True)

    class Meta:
        model = InvoiceItem
        fields = ["id", "variant", "variant_code", "product_name", "description", "qty", "price"]
        read_only_fields = ["description"]

    def get_variant_code(self, obj):
        return obj.variant.code if obj.variant_id else None


class PaymentLinkSerializer(serializers.ModelSerializer):
    phone_masked = serializers.SerializerMethodField()
    sent_by_name = serializers.SerializerMethodField()
    upi_check_label = serializers.CharField(source="get_upi_check_display", read_only=True)

    class Meta:
        model = PaymentLink
        fields = [
            "id", "phone_masked", "upi_check", "upi_check_label", "amount", "provider", "url",
            "status", "sent_by_name", "created_at", "paid_at", "provider_payment_id",
        ]

    def get_phone_masked(self, obj):
        return f"******{obj.phone[-4:]}"

    def get_sent_by_name(self, obj):
        return obj.sent_by.get_full_name() or obj.sent_by.username


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True)
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    settled_by_name = serializers.SerializerMethodField()
    payment_links = PaymentLinkSerializer(many=True, read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    reference = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "source_label", "reference", "party", "party_name", "stock_point", "stock_point_name",
            "date", "status", "pay_method", "paid_on", "payment_reference", "settled_by_name",
            "recurring_interval", "recurring_next", "repair_ticket", "rental", "period_start", "period_end",
            "items", "total", "payment_links",
        ]
        # Payment details are only ever written by the settle action, so
        # every settlement goes through its validation and audit fields;
        # repair/rental links are only ever set by those modules.
        read_only_fields = [
            "code", "source", "paid_on", "payment_reference", "repair_ticket", "rental", "period_start", "period_end",
        ]

    def get_reference(self, obj):
        """What this invoice was raised for, in words, e.g. the repair
        ticket or the rental agreement and month."""
        if obj.source == Invoice.REPAIR and obj.repair_ticket_id:
            return f"Repair {obj.repair_ticket.code}" + (" (follow-up visit)" if obj.repair_reopen_id else "")
        if obj.source == Invoice.RENTAL and obj.rental_id:
            label = obj.rental.agreement_code or f"Rental #{obj.rental_id}"
            if obj.period_start and obj.period_end:
                return f"{label} · {obj.period_start:%d %b %Y} – {obj.period_end:%d %b %Y}"
            return label
        return None

    def get_settled_by_name(self, obj):
        return (obj.settled_by.get_full_name() or obj.settled_by.username) if obj.settled_by else None

    def validate_items(self, items):
        # This endpoint creates product sales only (repair/rental invoices
        # are raised by their own modules): every line is a stock variant.
        if not items:
            raise serializers.ValidationError("An invoice needs at least one item.")
        for item in items:
            if not item.get("variant"):
                raise serializers.ValidationError("Every sale line needs a product variant.")
            if item.get("price", 0) < 0:
                raise serializers.ValidationError("Prices can't be negative.")
        return items

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        validated_data.setdefault("status", Invoice.LINK_SENT)
        invoice = create_invoice(source=Invoice.SALE, lines=items, **validated_data)
        for item in items:
            # decrement shared stock at the point of sale -- this is what makes
            # stock "shared": a sale on any channel moves the same pool.
            Stock.objects.filter(
                variant=item["variant"], stock_point=invoice.stock_point
            ).update(quantity=F("quantity") - item["qty"])
        return invoice
