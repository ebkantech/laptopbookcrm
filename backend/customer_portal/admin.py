from django.contrib import admin

from .models import CustomerAccessToken, CustomerLoginEvent, CustomerMembership, CustomerProfile


class CustomerMembershipInline(admin.TabularInline):
    model = CustomerMembership
    extra = 0


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "phone_e164", "status", "activated_at", "locked_until"]
    list_filter = ["status"]
    search_fields = ["user__username", "user__first_name", "phone_e164"]
    readonly_fields = ["created_at", "activated_at", "failed_login_attempts", "locked_until"]
    inlines = [CustomerMembershipInline]


@admin.register(CustomerAccessToken)
class CustomerAccessTokenAdmin(admin.ModelAdmin):
    list_display = ["profile", "purpose", "created_at", "expires_at", "consumed_at", "revoked_at"]
    list_filter = ["purpose"]
    readonly_fields = ["token_hash", "created_at", "consumed_at", "revoked_at"]


@admin.register(CustomerLoginEvent)
class CustomerLoginEventAdmin(admin.ModelAdmin):
    list_display = ["profile", "event_type", "ip_address", "at"]
    list_filter = ["event_type"]
    readonly_fields = ["profile", "event_type", "identifier_hash", "ip_address", "user_agent", "at"]
