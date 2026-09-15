from django.db import transaction
from django.db.models import F
from rest_framework import serializers

from catalog.models import Stock
from .models import Invoice, InvoiceItem


class InvoiceItemSerializer(serializers.ModelSerializer):
    variant_code = serializers.CharField(source="variant.code", read_only=True)
    product_name = serializers.CharField(source="variant.product.display_name", read_only=True)

    class Meta:
        model = InvoiceItem
        fields = ["id", "variant", "variant_code", "product_name", "qty", "price"]


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True)
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "party", "party_name", "stock_point", "stock_point_name",
            "date", "status", "pay_method", "recurring_interval", "recurring_next",
            "items", "total",
        ]
        read_only_fields = ["code"]

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("An invoice needs at least one item.")
        return items

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        last = Invoice.objects.order_by("-id").first()
        next_num = 3320 + (last.id if last else 0) + 1
        validated_data["code"] = f"INV-{next_num}"
        validated_data.setdefault("status", Invoice.LINK_SENT)
        validated_data.setdefault("pay_method", "Razorpay link")
        invoice = Invoice.objects.create(**validated_data)
        for item in items:
            InvoiceItem.objects.create(invoice=invoice, **item)
            # decrement shared stock at the point of sale -- this is what makes
            # stock "shared": a sale on any channel moves the same pool.
            Stock.objects.filter(
                variant=item["variant"], stock_point=invoice.stock_point
            ).update(quantity=F("quantity") - item["qty"])
        return invoice
