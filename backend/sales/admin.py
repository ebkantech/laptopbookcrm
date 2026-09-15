from django.contrib import admin

from .models import Invoice, InvoiceItem


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["code", "party", "stock_point", "date", "status", "total"]
    list_filter = ["status", "stock_point"]
    inlines = [InvoiceItemInline]
