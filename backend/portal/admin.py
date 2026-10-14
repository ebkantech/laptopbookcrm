from django.contrib import admin

from .models import Feedback, PortalAccessLog, PortalInvite, PortalOtpAccessLog, PortalOtpIssue, WhatsAppDeliveryLog


@admin.register(PortalInvite)
class PortalInviteAdmin(admin.ModelAdmin):
    list_display = ["party", "created_at", "expires_at", "otp_expires_at", "last_verified_at", "revoked_at", "revoked_reason", "issued_by"]
    readonly_fields = ["token", "otp_digest", "failed_attempts"]


@admin.register(PortalOtpIssue)
class PortalOtpIssueAdmin(admin.ModelAdmin):
    # the encrypted code is never shown here -- staff read codes in the CRM (audited)
    list_display = ["invite", "sequence", "kind", "issued_at", "expires_at", "used_at", "superseded_at", "locked_at"]
    exclude = ["otp_ciphertext"]
    readonly_fields = ["invite", "ref", "sequence", "kind", "issued_at", "expires_at", "message", "used_at", "superseded_at", "locked_at"]


@admin.register(PortalOtpAccessLog)
class PortalOtpAccessLogAdmin(admin.ModelAdmin):
    list_display = ["at", "user", "party", "path", "codes_disclosed", "ip_address"]
    readonly_fields = list_display


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["party", "rating", "created_at"]
    list_filter = ["rating"]


@admin.register(PortalAccessLog)
class PortalAccessLogAdmin(admin.ModelAdmin):
    list_display = ["party", "ip_address", "created_at", "latitude", "longitude"]
    readonly_fields = ["party", "ip_address", "user_agent", "latitude", "longitude", "location_accuracy_m", "created_at"]


@admin.register(WhatsAppDeliveryLog)
class WhatsAppDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ["party", "status", "provider_message_id", "created_at", "updated_at"]
    list_filter = ["status"]
    readonly_fields = ["party", "provider_message_id", "created_at"]
