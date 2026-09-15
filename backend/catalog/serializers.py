from rest_framework import serializers

from .models import Part, PartStock, Product, Service, Stock, StockPoint, Variant


class StockPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockPoint
        fields = ["id", "slug", "name", "kind"]


class StockSerializer(serializers.ModelSerializer):
    stock_point = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Stock
        fields = ["stock_point", "quantity"]


class VariantSerializer(serializers.ModelSerializer):
    stock = StockSerializer(many=True, read_only=True)
    total_stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Variant
        fields = ["id", "code", "spec", "mrp", "sell_price", "cost", "stock", "total_stock"]


class ProductSerializer(serializers.ModelSerializer):
    variants = VariantSerializer(many=True, read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "brand", "model_name", "display_name", "processor", "hsn",
            "condition", "product_code", "variants",
        ]


class PartStockSerializer(serializers.ModelSerializer):
    stock_point = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = PartStock
        fields = ["stock_point", "quantity"]


class PartSerializer(serializers.ModelSerializer):
    stock = PartStockSerializer(many=True, read_only=True)

    class Meta:
        model = Part
        fields = ["id", "slug", "name", "compatible_brands", "stock"]


class ServiceSerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)

    class Meta:
        model = Service
        fields = ["id", "slug", "label", "segment", "charge", "part"]
