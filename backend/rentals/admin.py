from django.contrib import admin

from .models import Rental, RentalIssue


class RentalIssueInline(admin.TabularInline):
    model = RentalIssue
    extra = 0


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = ["party", "product_label", "monthly_fee", "months_paid", "tenure_months", "next_payment_date", "churn_score", "churn_band"]
    inlines = [RentalIssueInline]


@admin.register(RentalIssue)
class RentalIssueAdmin(admin.ModelAdmin):
    list_display = ["title", "rental", "status", "assigned_to", "raised_at"]
    list_filter = ["status"]
