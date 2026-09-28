import random
import string
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from parties.models import Party


def _generate_otp():
    return "".join(random.choices(string.digits, k=6))


class PortalInvite(models.Model):
    """
    One "send portal link" action from staff produces one of these:
    a unique link token (goes in the URL) and a separate 6-digit OTP
    (goes to the customer's phone) -- the customer needs BOTH to get
    in, which is the two-factor requirement. Expires after 30 minutes
    and can only ever be used once.
    """
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="portal_invites")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    otp_code = models.CharField(max_length=6, default=_generate_otp)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="portal_invites_sent")

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=30)
        super().save(*args, **kwargs)

    @property
    def is_valid(self) -> bool:
        return self.consumed_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"Invite for {self.party.name} ({'used' if self.consumed_at else 'active' if self.is_valid else 'expired'})"


class WhatsAppDeliveryLog(models.Model):
    """
    Task 3's delivery-status half: a real WhatsApp Business API provider
    posts back sent/delivered/read/failed against a message it sent
    (see notify.send_whatsapp) via a webhook -- this row is what that
    webhook writes to, and what a Party detail screen would read to show
    "did they actually get this" instead of just "we attempted to send
    it". provider_message_id is whatever id the provider returned when
    the message was sent (send_whatsapp's provider_id) -- the webhook
    payload references it, that's how a status update finds its row.

    Not wired to a live provider yet (Task 2's provider decision is still
    open), so today this only fills in when something POSTs to
    portal/whatsapp-webhook/ -- nothing does that automatically until a
    real provider is chosen.
    """
    SENT, DELIVERED, READ, FAILED = "sent", "delivered", "read", "failed"
    STATUS_CHOICES = [(SENT, "Sent"), (DELIVERED, "Delivered"), (READ, "Read"), (FAILED, "Failed")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="whatsapp_delivery_logs")
    provider_message_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=SENT)
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.party.name} -- {self.status}"


class Feedback(models.Model):
    """General feedback left by a customer through their portal -- not tied to any specific invoice/rental/repair."""
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="feedback")
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.party.name} -- {self.rating}/5"


class PortalAccessLog(models.Model):
    """
    One row every time a customer actually opens the portal -- logged
    the moment their OTP verifies, since that's a real request hitting
    our server regardless of anything else. IP address and user agent
    are always captured this way (standard web request metadata, no
    permission prompt involved). Precise lat/lng are the OTHER kind of
    location entirely -- they're only ever filled in if the customer's
    browser explicitly asked them "allow this site to see your
    location?" and they said yes; left null otherwise, which is
    itself informative (they were asked and declined, or weren't
    asked on that visit).
    """
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="portal_access_logs")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_accuracy_m = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.party.name} accessed portal from {self.ip_address or 'unknown IP'}"
