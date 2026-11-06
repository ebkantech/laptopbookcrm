from django.contrib import admin

from .models import Package, PackagePrice, Subscription, SubscriptionEvent


class PriceInline(admin.TabularInline):
    model = PackagePrice
    extra = 0


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ["name", "key", "sort_order"]
    inlines = [PriceInline]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["package", "months", "amount", "starts_on", "ends_on"]


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ["subscription", "text", "created_at"]
