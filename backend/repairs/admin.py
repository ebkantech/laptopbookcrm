from django.contrib import admin

from .models import Notification, RepairInvoice, RepairTicket


class NotificationInline(admin.TabularInline):
    model = Notification
    extra = 0


@admin.register(RepairTicket)
class RepairTicketAdmin(admin.ModelAdmin):
    list_display = ["code", "party", "brand", "model_name", "status", "stock_point", "total"]
    list_filter = ["status", "stock_point"]
    filter_horizontal = ["services"]
    inlines = [NotificationInline]


@admin.register(RepairInvoice)
class RepairInvoiceAdmin(admin.ModelAdmin):
    list_display = ["code", "ticket", "amount", "status", "date"]
