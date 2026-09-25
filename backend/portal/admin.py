from django.contrib import admin

from .models import Feedback, PortalAccessLog, PortalInvite


@admin.register(PortalInvite)
class PortalInviteAdmin(admin.ModelAdmin):
    list_display = ["party", "created_at", "expires_at", "consumed_at", "issued_by"]
    readonly_fields = ["token", "otp_code"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["party", "rating", "created_at"]
    list_filter = ["rating"]


@admin.register(PortalAccessLog)
class PortalAccessLogAdmin(admin.ModelAdmin):
    list_display = ["party", "ip_address", "created_at", "latitude", "longitude"]
    readonly_fields = ["party", "ip_address", "user_agent", "latitude", "longitude", "location_accuracy_m", "created_at"]
