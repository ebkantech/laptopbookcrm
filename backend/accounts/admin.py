from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Permission, Role, User


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
