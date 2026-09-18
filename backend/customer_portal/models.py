from django.conf import settings
from django.db import models
from django.utils import timezone

from parties.models import Party


class CustomerProfile(models.Model):
    PENDING, ACTIVE, DISABLED = "pending", "active", "disabled"
    STATUS_CHOICES = [
        (PENDING, "Pending activation"),
        (ACTIVE, "Active"),
        (DISABLED, "Disabled"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    phone_e164 = models.CharField(max_length=16, unique=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profiles_created",
    )

    class Meta:
        ordering = ["user__first_name", "phone_e164"]

    def __str__(self):
        return f"{self.user} ({self.phone_e164})"


class CustomerMembership(models.Model):
    OWNER, MEMBER, VIEWER = "owner", "member", "viewer"
    ROLE_CHOICES = [(OWNER, "Owner"), (MEMBER, "Member"), (VIEWER, "Viewer")]

    profile = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name="memberships")
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="portal_memberships")
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default=OWNER)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["party__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "party"], name="unique_customer_party_membership"),
        ]

    def __str__(self):
        return f"{self.profile} -> {self.party}"


class CustomerAccessToken(models.Model):
    ACTIVATION, PASSWORD_RESET = "activation", "password_reset"
    PURPOSE_CHOICES = [(ACTIVATION, "Account activation"), (PASSWORD_RESET, "Password reset")]

    profile = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name="access_tokens")
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_access_tokens_created",
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self):
        return not self.consumed_at and not self.revoked_at and timezone.now() < self.expires_at


class CustomerLoginEvent(models.Model):
    LOGIN_SUCCESS, LOGIN_FAILURE, LOGOUT, ACTIVATED, PASSWORD_RESET = (
        "login_success", "login_failure", "logout", "activated", "password_reset"
    )
    EVENT_CHOICES = [
        (LOGIN_SUCCESS, "Login success"),
        (LOGIN_FAILURE, "Login failure"),
        (LOGOUT, "Logout"),
        (ACTIVATED, "Account activated"),
        (PASSWORD_RESET, "Password reset"),
    ]

    profile = models.ForeignKey(
        CustomerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_events",
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    identifier_hash = models.CharField(max_length=64, blank=True, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-at"]
