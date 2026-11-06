from django.contrib import admin

from .models import Part, PartStock, Product, Service, Stock, StockPoint, Variant


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0


class StockInline(admin.TabularInline):
    model = Stock
    extra = 0
    fields = ["stock_point", "quantity", "location"]


@admin.register(StockPoint)
class StockPointAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "slug", "phone"]
    fields = ["name", "slug", "kind", "address", "phone", "gstin"]


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
    list_display = ["label", "segment", "charge", "part", "variant"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # only inventory parts that can actually be fitted: not laptops, serial-tracked
        if db_field.name == "variant":
            kwargs["queryset"] = (Variant.objects.select_related("product")
                                  .exclude(product__category=Product.LAPTOP).filter(product__serial_tracking=True))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
