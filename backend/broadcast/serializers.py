from rest_framework import serializers

from .models import Campaign, WhatsAppOrder


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = ["id", "title", "channel", "audience", "sent", "opened", "at"]
        read_only_fields = ["sent", "opened", "at"]


class WhatsAppOrderSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)

    class Meta:
        model = WhatsAppOrder
        fields = ["id", "party", "party_name", "text", "at", "status"]
        read_only_fields = ["at"]
