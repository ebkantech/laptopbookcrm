from django.contrib import admin

from .models import Message, Party


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "phone", "city", "joined"]
    search_fields = ["name", "phone", "email"]
    inlines = [MessageInline]
