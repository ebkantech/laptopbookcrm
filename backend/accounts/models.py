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
    # The one shop this staff account works from -- limits every
    # store-linked record they can see or touch (accounts.store_scope).
    # Set only by the Owner (UserViewSet.set_store); left empty, a non-owner
    # account sees no store's records. SET_NULL so removing a shop leaves
    # its staff unassigned (no access) rather than pointing anywhere else.
    stock_point = models.ForeignKey(
        "catalog.StockPoint", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_staff",
    )

    # Where this person works from. "store" accounts are bound to one shop
    # (stock_point). Field technicians belong to no shop and take on-site jobs
    # from any store; outsourced technicians are the same but external
    # (freelancers / partner companies) and can only be given jobs by an
    # Admin / Super Admin (permission leads.outsource).
    STORE, FIELD, OUTSOURCED = "store", "field", "outsourced"
    KIND_CHOICES = [(STORE, "Store staff"), (FIELD, "Field technician (any store)"), (OUTSOURCED, "Outsourced technician")]
    staff_kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=STORE)
    company = models.CharField(max_length=80, blank=True, help_text="Partner company / freelancer name for an outsourced technician.")

    @property
    def is_store_free(self):
        return self.staff_kind in (self.FIELD, self.OUTSOURCED)

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
        ("rental_changes_requested", "Customer requested changes to a rental agreement"),
        ("repair_approved", "Customer approved a repair estimate"),
        ("payment_received", "A payment was recorded (invoice or repair bill settled)"),
        ("parts_return", "Parts you took out must be returned to the store"),
        ("lead_parts_due", "A technician hasn't returned unused parts after a job closed"),
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


class ActivityLog(models.Model):
    """
    Staff Activity Logs: one row per meaningful action a signed-in staff
    account performed, recorded server-side by accounts.activity (never
    from a request body). Shown per staff member in Store Locator ->
    Staff list -> Logs, under the visibility rules in accounts.activity.

    `actor_privileged` is the actor's superuser status at the time, so a
    privileged entry stays hidden from non-superusers even if the account
    is later demoted. `source` tells live entries from ones copied out of
    the older repair / rental histories and the permission-denied log when
    this table was introduced -- nothing else is reconstructed.
    """
    LIVE, IMPORTED = "live", "imported"
    SOURCE_CHOICES = [(LIVE, "Recorded by Activity Logs"), (IMPORTED, "Copied from an earlier history")]
    SUCCESS, DENIED = "success", "denied"
    OUTCOME_CHOICES = [(SUCCESS, "Completed"), (DENIED, "Blocked by permissions")]

    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="activity_logs")
    actor_privileged = models.BooleanField(default=False)
    at = models.DateTimeField(db_index=True)
    module = models.CharField(max_length=20)
    action = models.CharField(max_length=40)
    description = models.CharField(max_length=300)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default=SUCCESS)
    record_type = models.CharField(max_length=40, blank=True)
    record_id = models.CharField(max_length=40, blank=True)
    record_label = models.CharField(max_length=120, blank=True)
    # where it happened, when that can be told from the record; never guessed
    stock_point = models.ForeignKey("catalog.StockPoint", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # the actor's own Store Location at that moment (a fact about the actor,
    # not about the record) -- lets store-scoped viewers see store-less work
    # (e.g. a customer edit) done while the actor worked at their store,
    # without ever assigning a store to the record. Unknown for older rows.
    actor_stock_point = models.ForeignKey("catalog.StockPoint", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # {field: [before, after]} for edits -- secrets never stored, personal fields masked
    changes = models.JSONField(default=dict, blank=True)
    endpoint = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=LIVE)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-at"], name="activity_actor_at"),
            models.Index(fields=["actor", "module"], name="activity_actor_module"),
        ]

    def __str__(self):
        return f"{self.actor} {self.action} {self.record_type}:{self.record_id} at {self.at:%Y-%m-%d %H:%M}"
