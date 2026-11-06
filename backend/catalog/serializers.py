import re

from django.utils.text import slugify
from rest_framework import serializers

from .models import Part, PartStock, Product, Service, Stock, StockPoint, Variant

PHONE_RE = re.compile(r"^\+?[\d\s\-()]+$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class StockPointSerializer(serializers.ModelSerializer):
    """
    One shop / online channel -- the single record every stock row, staff
    assignment, repair ticket, invoice and rental asset points at by id.
    Editing it changes what all of them display; the id never changes.

    `slug` is set once at creation (generated from the name when omitted)
    and is read-only afterwards: the dashboard channel filter, the invoice
    stock lookup and the import/seed commands refer to stock points by it.
    """
    slug = serializers.CharField(max_length=32, required=False, allow_blank=True)

    class Meta:
        model = StockPoint
        fields = ["id", "slug", "name", "kind", "address", "phone", "gstin", "is_active"]
        # changed only through StockPointViewSet.set_status (its own permission + audit line)
        read_only_fields = ["is_active"]

    def to_representation(self, instance):
        # Active / Inactive is administrator information (catalog.status):
        # left out entirely for everyone else, and whenever there's no
        # request to tell who is asking.
        from .status import can_manage_status

        data = super().to_representation(instance)
        request = self.context.get("request")
        if not (request and can_manage_status(request.user)):
            data.pop("is_active", None)
        return data

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Enter the store or channel name.")
        clash = StockPoint.objects.filter(name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f"Another store or channel is already called “{value}”.")
        return value

    def validate_slug(self, value):
        value = value.strip().lower()
        if self.instance:
            if value and value != self.instance.slug:
                raise serializers.ValidationError(
                    "A store's code can't be changed once created -- dashboard filters and imports refer to it."
                )
            return self.instance.slug
        if value:
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
                raise serializers.ValidationError("Use lowercase letters, digits and single hyphens only (e.g. karol-bagh).")
            if StockPoint.objects.filter(slug=value).exists():
                raise serializers.ValidationError(f"The code “{value}” is already used by another store or channel.")
        return value

    def validate_address(self, value):
        return "\n".join(line.strip() for line in value.strip().splitlines())

    def validate_phone(self, value):
        value = value.strip()
        # a value already on file is kept as-is, so an older record never
        # blocks an unrelated edit (e.g. renaming the store)
        if not value or (self.instance and value == self.instance.phone):
            return value
        digits = re.sub(r"\D", "", value)
        if not PHONE_RE.match(value) or not 7 <= len(digits) <= 15:
            raise serializers.ValidationError("Enter a valid phone number (7–15 digits; +, spaces, hyphens allowed).")
        return value

    def validate_gstin(self, value):
        value = value.strip().upper()
        if not value or (self.instance and value == self.instance.gstin):
            return value
        if not GSTIN_RE.match(value):
            raise serializers.ValidationError("Enter a valid 15-character GSTIN (e.g. 07ABCDE1234F1Z5), or leave it blank.")
        return value

    def validate(self, attrs):
        sp = self.instance
        if sp is None and not attrs.get("slug"):
            attrs["slug"] = self._unique_slug(attrs.get("name", ""))
        if sp and sp.kind == StockPoint.SHOP and attrs.get("kind") == StockPoint.ONLINE:
            # staff can only be assigned to, and repairs only booked at, a physical shop
            blockers = []
            if sp.assigned_staff.exists():
                blockers.append("staff are assigned to it")
            if sp.repair_tickets.exists():
                blockers.append("it has repair tickets")
            if blockers:
                raise serializers.ValidationError({
                    "kind": f"{sp.name} can't become an online channel while {' and '.join(blockers)}.",
                })
        return attrs

    @staticmethod
    def _unique_slug(name):
        base = slugify(name)[:28].strip("-") or "store"
        slug, n = base, 2
        while StockPoint.objects.filter(slug=slug).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug


class StockSerializer(serializers.ModelSerializer):
    stock_point = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    stock_point_kind = serializers.CharField(source="stock_point.kind", read_only=True)

    class Meta:
        model = Stock
        fields = ["id", "stock_point", "stock_point_name", "stock_point_kind", "quantity", "location"]


class StoreStockRowSerializer(serializers.ModelSerializer):
    """One variant's stock at a single stock point, flattened for the Store Locator (no cost price)."""
    variant_id = serializers.IntegerField(source="variant.id", read_only=True)
    variant_code = serializers.CharField(source="variant.code", read_only=True)
    spec = serializers.CharField(source="variant.spec", read_only=True)
    mrp = serializers.IntegerField(source="variant.mrp", read_only=True)
    sell_price = serializers.IntegerField(source="variant.sell_price", read_only=True)
    product_id = serializers.IntegerField(source="variant.product.id", read_only=True)
    product_name = serializers.CharField(source="variant.product.display_name", read_only=True)
    brand = serializers.CharField(source="variant.product.brand", read_only=True)
    model_name = serializers.CharField(source="variant.product.model_name", read_only=True)
    product_code = serializers.CharField(source="variant.product.product_code", read_only=True)
    processor = serializers.CharField(source="variant.product.processor", read_only=True)
    condition = serializers.CharField(source="variant.product.condition", read_only=True)

    class Meta:
        model = Stock
        fields = [
            "id", "quantity", "location", "variant_id", "variant_code", "spec", "mrp", "sell_price",
            "product_id", "product_name", "brand", "model_name", "product_code", "processor", "condition",
        ]


class VariantSerializer(serializers.ModelSerializer):
    stock = StockSerializer(many=True, read_only=True)
    total_stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Variant
        fields = ["id", "code", "spec", "colour", "mrp", "sell_price", "cost", "cost_estimated", "stock", "total_stock"]


class ProductSerializer(serializers.ModelSerializer):
    variants = VariantSerializer(many=True, read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "brand", "model_name", "display_name", "processor", "hsn",
            "condition", "product_code", "category", "description", "specs", "serial_tracking", "variants",
        ]
        # set only by Inventory -> Add stock -> New product (catalog.new_product), which validates them
        read_only_fields = ["category", "specs", "serial_tracking"]


class PartStockSerializer(serializers.ModelSerializer):
    stock_point = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = PartStock
        fields = ["stock_point", "quantity"]


class PartSerializer(serializers.ModelSerializer):
    stock = PartStockSerializer(many=True, read_only=True)

    class Meta:
        model = Part
        fields = ["id", "slug", "name", "compatible_brands", "cost", "stock"]
        read_only_fields = ["cost"]  # set through the cost review (catalog.cost_views)


class ServiceSerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)

    class Meta:
        model = Service
        fields = ["id", "slug", "label", "segment", "charge", "part", "variant"]
