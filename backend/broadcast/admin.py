from django.contrib import admin

from .models import Campaign, WhatsAppOrder


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["title", "channel", "audience", "sent", "opened", "at"]


@admin.register(WhatsAppOrder)
class WhatsAppOrderAdmin(admin.ModelAdmin):
    list_display = ["party", "status", "at"]
