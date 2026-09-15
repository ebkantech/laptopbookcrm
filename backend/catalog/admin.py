from django.contrib import admin

from .models import Part, PartStock, Product, Service, Stock, StockPoint, Variant


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0


class StockInline(admin.TabularInline):
    model = Stock
    extra = 0


@admin.register(StockPoint)
class StockPointAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "slug"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["display_name", "product_code", "hsn", "condition"]
    search_fields = ["brand", "model_name", "product_code"]
    inlines = [VariantInline]


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ["code", "product", "spec", "sell_price", "total_stock"]
    inlines = [StockInline]


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]


@admin.register(PartStock)
class PartStockAdmin(admin.ModelAdmin):
    list_display = ["part", "stock_point", "quantity"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["label", "segment", "charge", "part"]
