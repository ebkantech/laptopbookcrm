from django.contrib import admin

from .models import DashboardLayout, DashboardLayoutItem, DashboardWidget


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "kind", "section", "default_order", "default_width", "is_active")
    list_filter = ("kind", "section", "is_active")
    search_fields = ("key", "title")


class DashboardLayoutItemInline(admin.TabularInline):
    model = DashboardLayoutItem
    extra = 0


@admin.register(DashboardLayout)
class DashboardLayoutAdmin(admin.ModelAdmin):
    list_display = ("__str__", "role", "user", "updated_at")
    inlines = [DashboardLayoutItemInline]
