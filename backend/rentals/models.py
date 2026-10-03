import calendar
import uuid
from datetime import date

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from parties.models import Party


def add_months(d: date, months: int) -> date:
    """Calendar-correct month addition (handles Jan 31 + 1mo -> Feb 28/29, etc.)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class Rental(models.Model):
    DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, ACTIVE, CLOSED, CANCELLED = (
        "draft", "pending_approval", "approved", "rejected", "active", "closed", "cancelled",
    )
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (PENDING_APPROVAL, "Pending customer approval"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (ACTIVE, "Active"),
        (CLOSED, "Closed"),
        (CANCELLED, "Cancelled"),
    ]

    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="rentals")
    product_label = models.CharField(max_length=120, help_text="Free-text device description, e.g. 'Dell Latitude 5420'.")
    monthly_fee = models.PositiveIntegerField()
    start = models.DateField()
    tenure_months = models.PositiveIntegerField()
    months_paid = models.PositiveIntegerField(default=0)
    late_count = models.PositiveIntegerField(default=0)
    tickets = models.PositiveIntegerField(default=0, help_text="Support tickets raised during the tenure -- kept in sync with RentalIssue count.")
    last_payment = models.DateField()
    # New agreement fields. Legacy single-rental columns above remain in place
    # so existing customer data and integrations continue to work.
    agreement_code = models.CharField(max_length=24, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    terms = models.TextField(blank=True)

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return self.agreement_code or f"{self.party.name} -- {self.product_label}"

    @property
    def rental_type(self):
        """A derived value: staff cannot accidentally label one item as Bulk."""
        line_count = getattr(self, "_line_count", None)
        if line_count is None:
            line_count = self.lines.count()
        return "bulk" if line_count >= 2 else "single"

    @property
    def total_monthly_fee(self):
        lines = getattr(self, "_prefetched_objects_cache", {}).get("lines")
        if lines is not None:
            # same fallback as below: a legacy rental with no lines bills
            # its own monthly_fee, not 0
            return sum(line.monthly_fee for line in lines) if lines else self.monthly_fee
        total = self.lines.aggregate(total=models.Sum("monthly_fee"))["total"]
        # Existing records have no RentalLine until they are migrated by staff.
        return total if total is not None else self.monthly_fee

    @property
    def next_payment_date(self) -> date:
        """Billing is monthly -- next due date is exactly one month after the last payment."""
        return add_months(self.last_payment, 1)

    @property
    def next_payment_overdue(self) -> bool:
        return date.today() > self.next_payment_date

    @property
    def churn_score(self) -> int:
        overdue_days = max(0, (date.today() - self.last_payment).days - 30)
        tenure_left = self.tenure_months - self.months_paid
        score = self.late_count * 14 + self.tickets * 9 + overdue_days * 1.4
        if tenure_left <= 1:
            score += 15
        return max(4, min(96, round(score)))

    @property
    def churn_band(self) -> str:
        s = self.churn_score
        if s >= 60:
            return "High risk"
        if s >= 32:
            return "Watch"
        return "Healthy"


class RentalIssue(models.Model):
    """
    A complaint or service request the client raised about their
    rented equipment -- assigned to a staff member, who resolves it by
    chatting with the client directly (over the party's WhatsApp
    thread -- see parties.Message).
    """
    OPEN, IN_PROGRESS, RESOLVED = "Open", "In progress", "Resolved"
    STATUS_CHOICES = [(OPEN, "Open"), (IN_PROGRESS, "In progress"), (RESOLVED, "Resolved")]

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name="issues")
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=OPEN)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_rental_issues")
    raised_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-raised_at"]

    def __str__(self):
        return f"{self.title} ({self.rental})"


class RentalAsset(models.Model):
    """One physical laptop. Assets are tracked individually, never only by stock quantity."""

    AVAILABLE, RESERVED, RENTED, MAINTENANCE, RETIRED = (
        "available", "reserved", "rented", "maintenance", "retired",
    )
    STATUS_CHOICES = [
        (AVAILABLE, "Available"), (RESERVED, "Reserved"), (RENTED, "Rented"),
        (MAINTENANCE, "Maintenance"), (RETIRED, "Retired"),
    ]

    asset_tag = models.CharField(max_length=48, unique=True)
    serial_number = models.CharField(max_length=80, unique=True)
    brand = models.CharField(max_length=40)
    model_name = models.CharField(max_length=80)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the unit was taken out of sale stock in Inventory to be
    # rented (RentalAssetViewSet.from_inventory) -- which product variant
    # it is and which shop's shelf it left.
    variant = models.ForeignKey("catalog.Variant", on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_assets")
    source_stock_point = models.ForeignKey("catalog.StockPoint", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["asset_tag"]

    def __str__(self):
        return f"{self.asset_tag} — {self.brand} {self.model_name}"


class RentalLine(models.Model):
    """One physical device and its negotiated monthly rate within an agreement."""

    # Functional checks done before handover, in display order.
    CHECKS = [
        ("power", "Powers on and boots"),
        ("display", "Display (no dead pixels / lines)"),
        ("keyboard", "Keyboard"),
        ("touchpad", "Touchpad"),
        ("battery", "Battery holds charge"),
        ("wifi", "Wi-Fi / network"),
        ("ports", "USB and charging ports"),
        ("camera_mic", "Camera and microphone"),
        ("speakers", "Speakers / audio"),
    ]

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(RentalAsset, on_delete=models.PROTECT, related_name="rental_lines")
    monthly_fee = models.PositiveIntegerField()

    # -- Handover record: the state the device leaves the shop in. All of
    # it goes into the customer's approval snapshot (see services._snapshot),
    # and an approval link can't be issued until handover_issues() is empty.
    checks = models.JSONField(default=dict, blank=True, help_text="{check_key: true/false} for CHECKS.")
    working_confirmed = models.BooleanField(default=False, help_text="Staff confirm the device was tested and is in working condition.")
    condition_notes = models.TextField(blank=True, help_text="Cosmetic condition: scratches, dents, wear.")
    accessories = models.JSONField(default=list, blank=True, help_text='[{"name": "Charger", "serial": ""}]')
    warranty_included = models.BooleanField(default=False)
    warranty_months = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Blank = the whole tenure.")
    warranty_terms = models.TextField(blank=True, help_text="The shop's own warranty conditions for this device.")
    handover_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    handover_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["rental", "asset"], name="one_asset_per_rental_agreement"),
        ]

    @property
    def description(self):
        return f"{self.asset.brand} {self.asset.model_name}"

    def handover_issues(self):
        """What's still missing before this device can go to the customer
        for approval -- an empty list means the handover is complete."""
        issues = []
        failed = [label for key, label in self.CHECKS if self.checks.get(key) is not True]
        if failed:
            issues.append(f"Not checked: {', '.join(failed)}")
        if not self.working_confirmed:
            issues.append("Confirm the device is tested and in working condition")
        kinds = {photo.kind for photo in self.photos.all()}
        missing = [label for kind, label in RentalLinePhoto.REQUIRED_KINDS if kind not in kinds]
        if missing:
            issues.append(f"Photos missing: {', '.join(missing)}")
        if self.accessories and RentalLinePhoto.ACCESSORY not in kinds:
            issues.append("Add a photo of the accessories being handed over")
        if self.warranty_included and not self.warranty_terms.strip():
            issues.append("Write the warranty conditions, or switch warranty off")
        return issues


def rental_photo_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "jpg").lower()[:5]
    return f"rental-handover/{instance.line.rental_id}/{instance.line_id}/{instance.kind}-{uuid.uuid4().hex[:12]}.{ext}"


class RentalLinePhoto(models.Model):
    """A handover photo of one rented device or its accessories. Served
    only to staff, or via the customer's own approval link -- never from
    a public URL (see rentals.views)."""

    FRONT, LID, LEFT, RIGHT, BASE, SERIAL = "front", "lid", "left", "right", "base", "serial"
    KEYBOARD, SCREEN_ON, ACCESSORY, OTHER = "keyboard", "screen_on", "accessory", "other"
    KIND_CHOICES = [
        (FRONT, "Front (screen side)"),
        (LID, "Back / lid"),
        (LEFT, "Left side"),
        (RIGHT, "Right side"),
        (BASE, "Bottom / base"),
        (SERIAL, "Serial number label"),
        (KEYBOARD, "Keyboard"),
        (SCREEN_ON, "Screen switched on"),
        (ACCESSORY, "Accessories"),
        (OTHER, "Other"),
    ]
    # Every side of the device plus its serial label is mandatory.
    REQUIRED_KINDS = KIND_CHOICES[:6]

    line = models.ForeignKey(RentalLine, on_delete=models.CASCADE, related_name="photos")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    caption = models.CharField(max_length=120, blank=True)
    image = models.FileField(upload_to=rental_photo_path)
    content_type = models.CharField(max_length=40)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class RentalApproval(models.Model):
    """Immutable 24-hour customer-approval snapshot for the whole agreement."""

    PENDING, APPROVED, REJECTED, EXPIRED, REVOKED = "pending", "approved", "rejected", "expired", "revoked"
    STATUS_CHOICES = [(value, value.title()) for value in (PENDING, APPROVED, REJECTED, EXPIRED, REVOKED)]
    CUSTOMER, ADMIN, SUPERADMIN = "customer", "admin", "superadmin"
    SOURCE_CHOICES = [
        (CUSTOMER, "Customer via secure link"),
        (ADMIN, "Admin on behalf of customer"),
        (SUPERADMIN, "Super Admin override"),
    ]

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name="approvals")
    version = models.PositiveSmallIntegerField()
    snapshot = models.JSONField(default=dict, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_approvals_requested")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_approvals_decided")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    # Evidentiary trail for the customer's own decision -- who clicked
    # Approve/Reject, from where, on what device. Only ever set by
    # customer_decide() (the public secure-link flow); an admin override
    # via approve_on_behalf() has decided_by instead, which is the more
    # relevant record for that path.
    decided_ip = models.GenericIPAddressField(null=True, blank=True)
    decided_user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["rental", "version"], name="unique_rental_approval_version"),
            models.UniqueConstraint(fields=["rental"], condition=Q(status="pending"), name="one_pending_rental_approval"),
            models.UniqueConstraint(fields=["rental"], condition=Q(status="approved"), name="one_approved_rental_approval"),
        ]

    @property
    def effective_status(self):
        if self.status == self.PENDING and self.expires_at and timezone.now() >= self.expires_at:
            return self.EXPIRED
        return self.status


class RentalEvent(models.Model):
    AGREEMENT_CREATED = "agreement_created"
    APPROVAL_LINK_CREATED = "approval_link_created"
    APPROVAL_DECIDED = "approval_decided"
    MODIFIED_AFTER_APPROVAL = "modified_after_approval"
    AGREEMENT_CANCELLED = "agreement_cancelled"
    AGREEMENT_CLOSED = "agreement_closed"
    HANDOVER_UPDATED = "handover_updated"
    EVENT_CHOICES = [
        (AGREEMENT_CREATED, "Agreement created"),
        (APPROVAL_LINK_CREATED, "Approval link created"),
        (APPROVAL_DECIDED, "Approval decided"),
        (MODIFIED_AFTER_APPROVAL, "Modified internally after approval"),
        (AGREEMENT_CANCELLED, "Agreement cancelled"),
        (AGREEMENT_CLOSED, "Agreement closed"),
        (HANDOVER_UPDATED, "Device handover details changed"),
    ]

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name="events")
    approval = models.ForeignKey(RentalApproval, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_events")
    metadata = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["at", "id"]
