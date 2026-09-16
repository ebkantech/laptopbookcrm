from django.contrib import admin

from .models import (
    Notification,
    RepairApproval,
    RepairEstimate,
    RepairEstimateLine,
    RepairInvoice,
    RepairOrder,
    RepairOrderApproval,
    RepairTicket,
    RepairTicketEvent,
)


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


class RepairEstimateLineInline(admin.TabularInline):
    model = RepairEstimateLine
    extra = 0
    readonly_fields = ["description", "quantity", "unit_price"]


@admin.register(RepairEstimate)
class RepairEstimateAdmin(admin.ModelAdmin):
    list_display = ["ticket", "version", "total_amount", "is_current", "created_at"]
    list_filter = ["is_current"]
    readonly_fields = ["ticket", "version", "created_at"]
    inlines = [RepairEstimateLineInline]


@admin.register(RepairApproval)
class RepairApprovalAdmin(admin.ModelAdmin):
    list_display = ["estimate", "status", "source", "sent_to_phone", "expires_at", "decided_at"]
    list_filter = ["status", "source"]
    readonly_fields = ["token_hash", "created_at", "expires_at", "decided_at"]


@admin.register(RepairTicketEvent)
class RepairTicketEventAdmin(admin.ModelAdmin):
    list_display = ["ticket", "event_type", "actor", "at"]
    list_filter = ["event_type"]
    readonly_fields = ["ticket", "estimate", "event_type", "actor", "metadata", "at"]


@admin.register(RepairOrder)
class RepairOrderAdmin(admin.ModelAdmin):
    list_display = ["code", "party", "repair_type", "created_by", "created_at"]
    readonly_fields = ["code", "created_by", "created_at"]


@admin.register(RepairOrderApproval)
class RepairOrderApprovalAdmin(admin.ModelAdmin):
    list_display = ["order", "version", "status", "source", "expires_at", "decided_at"]
    list_filter = ["status", "source"]
    readonly_fields = ["order", "version", "snapshot", "token_hash", "created_at", "expires_at", "decided_at"]
