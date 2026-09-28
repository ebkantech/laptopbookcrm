from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import NotificationRule, Permission, PermissionDeniedLog, Role, StaffNotification, User


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["codename", "description"]
    search_fields = ["codename", "description"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["label", "slug"]
    filter_horizontal = ["permissions"]


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "first_name", "last_name", "role", "is_staff"]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Role & contact", {"fields": ("role", "phone")}),
    )


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = ["event_key", "role", "via_email", "via_whatsapp", "via_inapp"]
    list_filter = ["event_key", "role"]


@admin.register(StaffNotification)
class StaffNotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "subject", "event_key", "created_at", "read_at"]
    list_filter = ["event_key"]
    search_fields = ["user__username", "subject"]
    readonly_fields = ["user", "event_key", "subject", "body", "created_at"]


@admin.register(PermissionDeniedLog)
class PermissionDeniedLogAdmin(admin.ModelAdmin):
    list_display = ["user", "required_perm", "method", "path", "at"]
    list_filter = ["required_perm"]
    search_fields = ["user__username", "required_perm", "path"]
    readonly_fields = ["user", "path", "method", "required_perm", "at"]
