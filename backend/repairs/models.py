from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from catalog.models import Service, StockPoint
from parties.models import Party


DEFAULT_APPROVAL_TERMS = (
    "I approve the final repair work and total amount shown in this estimate. "
    "Any later change will be coordinated separately with the service centre."
)


class RepairOrder(models.Model):
    """One customer drop-off containing one (single) or several (bulk) devices."""

    code = models.CharField(max_length=24, unique=True, null=True, blank=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="repair_orders")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_orders_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def repair_type(self):
        return "bulk" if self.tickets.count() >= 2 else "single"

    def __str__(self):
        return self.code or f"Repair order {self.pk}"


class RepairTicket(models.Model):
    RECEIVED, DIAGNOSING, IN_PROGRESS, READY, DELIVERED = (
        "Received", "Diagnosing", "In progress", "Ready for pickup", "Delivered",
    )
    STAGES = [RECEIVED, DIAGNOSING, IN_PROGRESS, READY, DELIVERED]
    STATUS_CHOICES = [(s, s) for s in STAGES]

    ADVANCE, FULL = "advance", "full"
    PAYMENT_CHOICES = [(ADVANCE, "25% advance"), (FULL, "Pay on delivery")]

    code = models.CharField(max_length=20, unique=True)
    order = models.ForeignKey(
        RepairOrder,
        on_delete=models.PROTECT,
        related_name="tickets",
        null=True,
        blank=True,
    )
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="repair_tickets")
    brand = models.CharField(max_length=40)
    model_name = models.CharField(max_length=80)
    serial = models.CharField(max_length=60, blank=True, default="\u2014")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="repair_tickets")
    issue = models.TextField()
    services = models.ManyToManyField(Service, related_name="tickets")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=RECEIVED)
    received = models.DateField()
    expected = models.DateField(null=True, blank=True)
    payment = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default=ADVANCE)
    advance_paid = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-received", "-id"]

    def __str__(self):
        return self.code

    @property
    def total(self):
        estimate = self.current_estimate
        if estimate:
            return estimate.total_amount
        return sum(s.charge for s in self.services.all())

    @property
    def balance_due(self):
        return self.total - self.advance_paid

    def next_stage(self):
        idx = self.STAGES.index(self.status)
        return self.STAGES[idx + 1] if idx + 1 < len(self.STAGES) else None

    @property
    def current_estimate(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("estimates")
        if prefetched is not None:
            return next((estimate for estimate in prefetched if estimate.is_current), None)
        return self.estimates.filter(is_current=True).first()

    @property
    def has_repair_approval(self):
        estimate = self.current_estimate
        return bool(estimate and estimate.is_approved)

    @property
    def original_invoice(self):
        return self.invoices.filter(reopen__isnull=True).first()

    @property
    def active_reopen(self):
        """The most recent reopen that hasn't been settled yet, if any."""
        return self.reopens.filter(invoice__isnull=True).first()


class RepairEstimate(models.Model):
    """Immutable snapshot of the exact work and price presented for approval."""

    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="estimates")
    version = models.PositiveSmallIntegerField()
    is_current = models.BooleanField(default=True)
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=20)
    device_brand = models.CharField(max_length=40)
    device_model = models.CharField(max_length=80)
    device_serial = models.CharField(max_length=60, blank=True)
    reported_issue = models.TextField()
    currency = models.CharField(max_length=3, default="INR")
    total_amount = models.PositiveIntegerField()
    advance_paid = models.PositiveIntegerField(default=0)
    terms = models.TextField(default=DEFAULT_APPROVAL_TERMS)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_estimates_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["ticket", "version"], name="unique_repair_estimate_version"),
            models.UniqueConstraint(
                fields=["ticket"], condition=Q(is_current=True), name="one_current_repair_estimate"
            ),
        ]

    @property
    def balance_due(self):
        return max(0, self.total_amount - self.advance_paid)

    def _approval_records(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("approvals")
        return list(prefetched) if prefetched is not None else list(self.approvals.all())

    @property
    def approved_record(self):
        approved = [row for row in self._approval_records() if row.status == RepairApproval.APPROVED]
        return max(approved, key=lambda row: row.decided_at or row.created_at, default=None)

    @property
    def latest_approval(self):
        approved = self.approved_record
        if approved:
            return approved
        return max(self._approval_records(), key=lambda row: row.created_at, default=None)

    @property
    def is_approved(self):
        return self.approved_record is not None

    @property
    def approval_status(self):
        approval = self.latest_approval
        if not approval:
            return "not_sent"
        if approval.status == RepairApproval.APPROVED:
            return {
                RepairApproval.CUSTOMER: "customer_approved",
                RepairApproval.ADMIN: "admin_approved",
                RepairApproval.SUPERADMIN: "superadmin_approved",
            }.get(approval.source, "approved")
        return approval.effective_status


class RepairEstimateLine(models.Model):
    estimate = models.ForeignKey(RepairEstimate, on_delete=models.CASCADE, related_name="lines")
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_estimate_lines"
    )
    description = models.CharField(max_length=160)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="repair_estimate_quantity_gt_zero"),
        ]

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class RepairApproval(models.Model):
    PENDING, APPROVED, REJECTED, EXPIRED, REVOKED = "pending", "approved", "rejected", "expired", "revoked"
    STATUS_CHOICES = [(value, value.title()) for value in (PENDING, APPROVED, REJECTED, EXPIRED, REVOKED)]
    CUSTOMER, ADMIN, SUPERADMIN = "customer", "admin", "superadmin"
    SOURCE_CHOICES = [
        (CUSTOMER, "Customer via secure link"),
        (ADMIN, "Admin on behalf of customer"),
        (SUPERADMIN, "Super Admin override"),
    ]

    estimate = models.ForeignKey(RepairEstimate, on_delete=models.CASCADE, related_name="approvals")
    order_approval = models.ForeignKey(
        "RepairOrderApproval",
        on_delete=models.SET_NULL,
        related_name="ticket_approvals",
        null=True,
        blank=True,
    )
    token_hash = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, blank=True)
    sent_to_phone = models.CharField(max_length=20, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_approvals_requested")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_approvals_decided")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["estimate"], condition=Q(status="pending"), name="one_pending_repair_approval_link"),
            models.UniqueConstraint(fields=["estimate"], condition=Q(status="approved"), name="one_approved_repair_decision"),
        ]

    @property
    def effective_status(self):
        if self.status == self.PENDING and self.expires_at and timezone.now() >= self.expires_at:
            return self.EXPIRED
        return self.status


class RepairOrderApproval(models.Model):
    """Immutable combined approval snapshot for every device in a bulk order."""

    PENDING, APPROVED, REJECTED, EXPIRED, REVOKED = "pending", "approved", "rejected", "expired", "revoked"
    STATUS_CHOICES = [(value, value.title()) for value in (PENDING, APPROVED, REJECTED, EXPIRED, REVOKED)]
    CUSTOMER, ADMIN, SUPERADMIN = "customer", "admin", "superadmin"
    SOURCE_CHOICES = [
        (CUSTOMER, "Customer via secure link"),
        (ADMIN, "Admin on behalf of customer"),
        (SUPERADMIN, "Super Admin override"),
    ]

    order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name="approvals")
    version = models.PositiveSmallIntegerField()
    snapshot = models.JSONField(default=dict, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_order_approvals_requested",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_order_approvals_decided",
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["order", "version"], name="unique_repair_order_approval_version"),
            models.UniqueConstraint(
                fields=["order"], condition=Q(status="pending"), name="one_pending_repair_order_approval"
            ),
            models.UniqueConstraint(
                fields=["order"], condition=Q(status="approved"), name="one_approved_repair_order_approval"
            ),
        ]

    @property
    def effective_status(self):
        if self.status == self.PENDING and self.expires_at and timezone.now() >= self.expires_at:
            return self.EXPIRED
        return self.status


class RepairTicketEvent(models.Model):
    TICKET_CREATED = "ticket_created"
    ESTIMATE_FINALIZED = "estimate_finalized"
    APPROVAL_LINK_CREATED = "approval_link_created"
    APPROVAL_DECIDED = "approval_decided"
    STAGE_CHANGED = "stage_changed"
    SETTLED = "settled"
    MODIFIED_AFTER_APPROVAL = "modified_after_approval"
    EVENT_CHOICES = [
        (TICKET_CREATED, "Ticket created"),
        (ESTIMATE_FINALIZED, "Estimate finalized"),
        (APPROVAL_LINK_CREATED, "Approval link created"),
        (APPROVAL_DECIDED, "Approval decided"),
        (STAGE_CHANGED, "Stage changed"),
        (SETTLED, "Settled"),
        (MODIFIED_AFTER_APPROVAL, "Modified internally after approval"),
    ]

    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="events")
    estimate = models.ForeignKey(RepairEstimate, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_ticket_events")
    metadata = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["at", "id"]


class RepairInvoice(models.Model):
    # was OneToOneField -- a ticket can now be settled more than once
    # (original delivery, then again after any reopen), so this is a
    # FK: one ticket, many invoices over its lifetime. `reopen` is set
    # for a reopen's bill, left null for the original delivery's bill.
    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="invoices")
    reopen = models.OneToOneField("RepairReopen", on_delete=models.CASCADE, null=True, blank=True, related_name="invoice")
    code = models.CharField(max_length=20, unique=True)
    amount = models.PositiveIntegerField()
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="repair_invoices")
    status = models.CharField(max_length=20, default="Paid")
    date = models.DateField()


class RepairReopen(models.Model):
    """
    A ticket coming back after delivery -- same device, not a new
    ticket (per the chosen policy: reopening puts the same
    RepairTicket back into "In progress"). Each reopen carries its own
    set of line items and, once settled, its own invoice -- billing
    for the follow-up visit never touches what was already charged
    and paid on the original delivery.
    """
    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="reopens")
    issue = models.TextField()
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-opened_at"]

    @property
    def total(self):
        return sum(i.charge for i in self.items.all())


class RepairReopenItem(models.Model):
    """
    One service requested on a reopen visit, with the charge actually
    applied -- not necessarily the service's list price. Free (0) when
    it's the same service that was already done on this ticket AND the
    device is still under an active repair warranty; full price for
    anything that wasn't part of the original job (a genuinely new
    problem or an untouched part). `covered_by_warranty` records which
    case applied, and the charge can still be hand-overridden by staff
    either way.
    """
    reopen = models.ForeignKey(RepairReopen, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="reopen_items")
    charge = models.PositiveIntegerField(default=0)
    covered_by_warranty = models.BooleanField(default=False)


class Notification(models.Model):
    WHATSAPP, EMAIL = "whatsapp", "email"
    CHANNEL_CHOICES = [(WHATSAPP, "WhatsApp"), (EMAIL, "Email")]

    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    text = models.CharField(max_length=240)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]
