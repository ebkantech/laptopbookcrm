import secrets
import string
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password

from parties.models import Party


def _generate_otp():
    return "".join(secrets.choice(string.digits) for _ in range(6))


class PortalInvite(models.Model):
    """
    One "send portal link" action from staff produces one of these:
    a unique link token (goes in the URL) and a separate hashed 6-digit OTP
    (goes to the customer's email) -- the customer needs BOTH to get
    in, which is the two-factor requirement.

    The LINK is reusable until expires_at (rental tenure end, or 24h for
    Dealer/Retail -- see portal.access) unless revoked_at is set. The
    CODE is single-use and expires at otp_expires_at (30 minutes); the
    customer can request a fresh one from the same link. A verified code
    is cleared (otp_digest = "") -- verifying never closes the link.

    consumed_at is legacy: it used to be stamped both on a successful
    login and on replacement. Migration 0005 copied it into revoked_at
    and nothing writes it any more.
    """
    REPLACED, ACCESS_REVOKED, LEGACY_CONSUMED = "replaced", "access_revoked", "legacy_consumed"
    REVOKED_REASON_CHOICES = [
        (REPLACED, "Replaced by a newer invitation"),
        (ACCESS_REVOKED, "Portal access revoked by staff"),
        (LEGACY_CONSUMED, "Used or replaced under the old single-use rule"),
    ]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="portal_invites")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    otp_digest = models.CharField(max_length=128, blank=True)
    # wrong codes against the CURRENT otp_digest; reset when a new code is issued
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    otp_issued_at = models.DateTimeField(null=True, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="When the invitation link itself stops working.")
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=20, choices=REVOKED_REASON_CHOICES, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="portal_invites_sent")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # the hourly creation limit and "revoke this party's open links"
            models.Index(fields=["party", "created_at"], name="portal_invite_party_created"),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Callers normally pass portal.access.invite_expiry_for(); this
            # is only the safe fallback for a bare create (24h, never longer).
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    @property
    def invite_expires_at(self):
        return self.expires_at

    @property
    def is_valid(self) -> bool:
        """The link is still usable (says nothing about whether a code is currently active)."""
        return self.revoked_at is None and self.consumed_at is None and timezone.now() < self.expires_at

    def set_otp(self, code):
        self.otp_digest = make_password(code)

    def check_otp(self, code):
        return bool(self.otp_digest) and check_password(code, self.otp_digest)

    def __str__(self):
        return f"Invite for {self.party.name} ({'revoked' if self.revoked_at or self.consumed_at else 'active' if self.is_valid else 'expired'})"


class PortalOtpIssue(models.Model):
    """
    One verification code that was actually emailed for an invite: the
    invitation's first code, then one row per successful customer resend.
    Each row has its own CRM history entry (`message`) and keeps the code
    encrypted (portal.otp_vault) so staff can read it back there for good.

    Display only -- nothing here is ever used to authenticate. Whether a
    code still WORKS is decided solely by PortalInvite.otp_digest; the
    used/superseded/locked stamps below only label history.
    """
    INVITATION, RESEND = "invitation", "resend"
    KIND_CHOICES = [(INVITATION, "Portal Invitation Generated"), (RESEND, "OTP Resent by Customer")]

    invite = models.ForeignKey(PortalInvite, on_delete=models.CASCADE, related_name="otp_issues")
    ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sequence = models.PositiveSmallIntegerField(help_text="1 = the invitation's own code, 2+ = resends.")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    otp_ciphertext = models.TextField(blank=True, editable=False)
    message = models.ForeignKey("parties.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    used_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["invite_id", "sequence"]
        constraints = [models.UniqueConstraint(fields=["invite", "sequence"], name="unique_portal_otp_issue_sequence")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.sequence} for invite {self.invite_id}"


class PortalOtpAccessLog(models.Model):
    """Who read plaintext portal codes in the CRM, when and from where (never the codes themselves)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="portal_otp_access_logs")
    path = models.CharField(max_length=200)
    codes_disclosed = models.PositiveSmallIntegerField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


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
