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
            "due_date", "cancel_reason", "cancelled_at", "cancelled_by_name",
            "items", "total", "payment_links",
        ]
        # Payment details are only ever written by the settle action, so
        # every settlement goes through its validation and audit fields;
        # repair/rental links are only ever set by those modules.
        read_only_fields = [
            "code", "source", "paid_on", "payment_reference", "repair_ticket", "rental", "period_start", "period_end",
            "cancel_reason", "cancelled_at", "status",
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

    cancelled_by_name = serializers.SerializerMethodField()

    def get_cancelled_by_name(self, obj):
        return (obj.cancelled_by.get_full_name() or obj.cancelled_by.username) if obj.cancelled_by else None

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
            if item.get("qty", 0) < 1:
                raise serializers.ValidationError("Quantity must be at least 1.")
        return items

    @staticmethod
    def _check_and_take_stock(items, stock_point):
        """Lock the shelf rows, refuse to sell more than is there (instead
        of the database refusing with a server error), then take the units."""
        wanted = {}
        for item in items:
            wanted[item["variant"]] = wanted.get(item["variant"], 0) + item["qty"]
        rows = {
            row.variant_id: row
            for row in Stock.objects.select_for_update().filter(stock_point=stock_point, variant__in=list(wanted))
        }
        problems = []
        for variant, qty in wanted.items():
            row = rows.get(variant.id)
            have = row.quantity if row else 0
            if have < qty:
                name = f"{variant.product.display_name} ({variant.spec})"
                problems.append(
                    f"{name}: only {have} in stock at {stock_point.name}" if row
                    else f"{name} isn't stocked at {stock_point.name}"
                )
        if problems:
            raise serializers.ValidationError({"items": problems})
        for variant, qty in wanted.items():
            Stock.objects.filter(pk=rows[variant.id].pk).update(quantity=F("quantity") - qty)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        validated_data["status"] = Invoice.LINK_SENT
        # take the units off the shared stock pool of the shop/channel sold
        # through -- a sale on any channel moves the same pool
        self._check_and_take_stock(items, validated_data["stock_point"])
        return create_invoice(source=Invoice.SALE, lines=items, **validated_data)
