from django.db import models

from parties.models import Party


class Campaign(models.Model):
    WHATSAPP, EMAIL = "whatsapp", "email"
    CHANNEL_CHOICES = [(WHATSAPP, "WhatsApp"), (EMAIL, "Email")]

    title = models.CharField(max_length=200)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    audience = models.CharField(max_length=120)
    sent = models.PositiveIntegerField(default=0)
    opened = models.PositiveIntegerField(default=0)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


class WhatsAppOrder(models.Model):
    NEW, QUOTED = "New", "Quoted"
    STATUS_CHOICES = [(NEW, "New"), (QUOTED, "Quoted")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="whatsapp_orders")
    text = models.TextField()
    at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=NEW)

    class Meta:
        ordering = ["-at"]
