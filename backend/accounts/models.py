from django.contrib.auth.models import AbstractUser
from django.db import models


class Permission(models.Model):
    """
    One row per named action in the system, e.g. 'cashbook.edit'.
    This is the vocabulary a Role draws from -- mirrors the PERMS
    dictionary from the prototype so the same access model carries
    over exactly.
    """
    codename = models.SlugField(max_length=64, unique=True)
    description = models.CharField(max_length=200)

    class Meta:
        ordering = ["codename"]

    def __str__(self):
        return self.codename


class Role(models.Model):
    """A named set of permissions -- Owner, Accountant, Store Manager, etc."""
    slug = models.SlugField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label

    def has_perm(self, codename: str) -> bool:
        return self.permissions.filter(codename=codename).exists()


class User(AbstractUser):
    """
    Staff account. `role` drives every permission check across the
    API -- see accounts.permissions.HasPerm.
    """
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def has_perm_code(self, codename: str) -> bool:
        if self.is_superuser:
            return True
        return bool(self.role and self.role.has_perm(codename))

    def __str__(self):
        return self.get_full_name() or self.username


class NotificationRule(models.Model):
    """
    Task 2: internal staff alerts -- which roles get pinged, and by
    which channel(s), when a business event fires. Deliberately
    separate from the CUSTOMER-facing send_whatsapp/send_email calls
    documented in docs/NOTIFICATIONS.md's "Role -> channel mapping"
    table (those tell a customer about their own repair/rental/order;
    this tells STAFF that something happened their role cares about).
    Configurable per (event, role) pair via the Settings > Staff
    alerts screen instead of hardcoded, so who gets alerted about what
    can change without a deploy. Both channels still go through
    notify.py's existing (currently simulated) senders -- wiring a
    real WhatsApp/email provider is Task 2's still-open provider
    decision, not something this mapping needs to wait on.
    """
    EVENT_CHOICES = [
        ("repair_ticket_created", "New repair ticket"),
        ("low_negative_feedback", "Low-rated customer feedback (2 stars or fewer)"),
        ("rental_approved", "Customer approved a rental agreement"),
        ("repair_approved", "Customer approved a repair estimate"),
        ("payment_received", "A payment was recorded (invoice or repair bill settled)"),
    ]
    event_key = models.CharField(max_length=40, choices=EVENT_CHOICES)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="notification_rules")
    via_email = models.BooleanField(default=True)
    via_whatsapp = models.BooleanField(default=False)
    via_inapp = models.BooleanField(default=True, help_text="Show in the header's notification bell for this role.")

    class Meta:
        ordering = ["event_key", "role__label"]
        unique_together = [("event_key", "role")]

    def __str__(self):
        channels = ", ".join(c for c, on in [("email", self.via_email), ("whatsapp", self.via_whatsapp), ("in-app", self.via_inapp)] if on) or "off"
        return f"{self.get_event_key_display()} → {self.role.label} ({channels})"


class StaffNotification(models.Model):
    """
    The in-app inbox behind the header's notification bell
    (frontend/src/components/PageHeader.jsx). One row per (user,
    event) -- written by crmbook_backend.notify.notify_staff()
    alongside the email/WhatsApp sends, gated by the same
    NotificationRule.via_inapp toggle on Settings > Staff alerts.
    Read state is per-user/per-row, never shared across the team.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_notifications")
    event_key = models.CharField(max_length=40, choices=NotificationRule.EVENT_CHOICES)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.subject}"


class PermissionDeniedLog(models.Model):
    """
    Task 6 security checklist: "every permission-denied attempt logged
    with who/when". Written by accounts.permissions.HasPerm whenever a
    logged-in staff account is blocked by a real required_perm check
    (not just "not logged in yet", which isn't a permission decision).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permission_denials")
    path = models.CharField(max_length=300)
    method = models.CharField(max_length=10)
    required_perm = models.CharField(max_length=64)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.user} denied {self.required_perm} at {self.at:%Y-%m-%d %H:%M}"
