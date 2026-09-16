from django.contrib import admin

from .models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalIssue, RentalLine


class RentalIssueInline(admin.TabularInline):
    model = RentalIssue
    extra = 0


class RentalLineInline(admin.TabularInline):
    model = RentalLine
    extra = 0
    autocomplete_fields = ["asset"]


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = ["agreement_code", "party", "product_label", "status", "monthly_fee", "months_paid", "tenure_months", "next_payment_date", "churn_score", "churn_band"]
    list_filter = ["status"]
    search_fields = ["agreement_code", "party__name", "product_label"]
    inlines = [RentalLineInline, RentalIssueInline]


@admin.register(RentalIssue)
class RentalIssueAdmin(admin.ModelAdmin):
    list_display = ["title", "rental", "status", "assigned_to", "raised_at"]
    list_filter = ["status"]


@admin.register(RentalAsset)
class RentalAssetAdmin(admin.ModelAdmin):
    list_display = ["asset_tag", "serial_number", "brand", "model_name", "status"]
    list_filter = ["status"]
    search_fields = ["asset_tag", "serial_number", "brand", "model_name"]


@admin.register(RentalApproval)
class RentalApprovalAdmin(admin.ModelAdmin):
    list_display = ["rental", "version", "status", "source", "expires_at", "decided_at"]
    list_filter = ["status", "source"]
    readonly_fields = ["snapshot", "token_hash", "created_at", "expires_at", "decided_at"]


@admin.register(RentalEvent)
class RentalEventAdmin(admin.ModelAdmin):
    list_display = ["rental", "event_type", "actor", "at"]
    list_filter = ["event_type"]
    readonly_fields = ["rental", "approval", "event_type", "actor", "metadata", "at"]
