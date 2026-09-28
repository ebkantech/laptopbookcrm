from django.contrib import admin

from .models import Message, Party


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "phone", "whatsapp_verified", "whatsapp_checked_at", "portal_access_revoked_at", "city", "joined"]
    list_filter = ["whatsapp_verified"]
    search_fields = ["name", "phone", "email"]
    readonly_fields = ["whatsapp_checked_at", "portal_access_revoked_at"]
    inlines = [MessageInline]
