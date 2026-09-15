from django.contrib import admin

from .models import Warranty


@admin.register(Warranty)
class WarrantyAdmin(admin.ModelAdmin):
    list_display = ["party", "section", "item_label", "start_date", "end_date", "status"]
    list_filter = ["section"]
    search_fields = ["party__name", "party__phone", "item_label"]
