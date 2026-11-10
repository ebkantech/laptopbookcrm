from django.conf import settings
from django.db import models

from catalog.models import Part, StockPoint, Variant
from parties.models import Party


class Lead(models.Model):
    """
    An on-site service job: staff visit the client, diagnose the laptop,
    quote, get the client's approval, do the work and collect payment.
    `lead_type` leaves room for other kinds of lead later; only on-site
    service is built so far.
    """
    ONSITE = "onsite"
    TYPE_CHOICES = [(ONSITE, "On-site service")]

    NEW, ASSIGNED, VISITING, DIAGNOSED, AWAITING, APPROVED = "new", "assigned", "visiting", "diagnosed", "awaiting_approval", "approved"
    IN_WORK, WORK_DONE, CLOSED, REJECTED, CANCELLED = "in_work", "work_done", "closed", "rejected", "cancelled"
    TO_STORE = "to_store"
    STATUS_CHOICES = [
        (NEW, "New"), (ASSIGNED, "Assigned"), (VISITING, "Visiting"), (DIAGNOSED, "Diagnosed"),
        (AWAITING, "Awaiting approval"), (APPROVED, "Approved"), (IN_WORK, "In work"),
        (WORK_DONE, "Work done - payment due"), (CLOSED, "Closed"), (REJECTED, "Rejected"), (CANCELLED, "Cancelled"), (TO_STORE, "Taken to store for repair"),
    ]
    OPEN = (NEW, ASSIGNED, VISITING, DIAGNOSED, AWAITING, APPROVED, IN_WORK, WORK_DONE)
    FINISHED = (CLOSED, REJECTED, CANCELLED, TO_STORE)

    LOW, NORMAL, URGENT = "low", "normal", "urgent"
    PRIORITY_CHOICES = [(LOW, "Low"), (NORMAL, "Normal"), (URGENT, "Urgent")]

    code = models.CharField(max_length=20, unique=True)
    lead_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=ONSITE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=NEW, db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=NORMAL)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="leads")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="leads")
    contact_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    site_address = models.CharField(max_length=300)
    map_url = models.URLField(blank=True)
    device = models.CharField(max_length=160, blank=True, help_text="Brand / model of the laptop(s).")
    issue = models.TextField()
    preferred_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_leads",
    )
    # Charged for the visit; invoiced on its own if the client rejects the quote.
    visit_charge = models.PositiveIntegerField(default=0)
    advance_amount = models.PositiveIntegerField(default=0, help_text="Optional advance asked of the client.")

    checked_in_at = models.DateTimeField(null=True, blank=True)
    check_in_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    diagnosis = models.TextField(blank=True)
    diagnosed_at = models.DateTimeField(null=True, blank=True)
    work_notes = models.TextField(blank=True)
    work_started_at = models.DateTimeField(null=True, blank=True)
    work_done_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    closed_on_credit = models.BooleanField(default=False)
    credit_reason = models.CharField(max_length=200, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    reject_reason = models.CharField(max_length=500, blank=True)

    # Set when the laptop could not be fixed on site and was taken to the
    # store: the in-house repair then runs as a normal Repairs ticket.
    repair_ticket = models.ForeignKey(
        "repairs.RepairTicket", on_delete=models.PROTECT, null=True, blank=True, related_name="onsite_leads",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.code


class LeadQuote(models.Model):
    """One immutable version of the bill. A change after approval is a new
    version that needs approving again."""
    DRAFT, SENT, APPROVED, REJECTED, SUPERSEDED = "draft", "sent", "approved", "rejected", "superseded"
    STATUS_CHOICES = [(DRAFT, "Draft"), (SENT, "Sent"), (APPROVED, "Approved"), (REJECTED, "Rejected"), (SUPERSEDED, "Superseded")]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="quotes")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT)
    note = models.CharField(max_length=300, blank=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="lead_quotes")
    on_behalf = models.BooleanField(default=False, help_text="Prepared by an admin for the assigned technician.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["lead_id", "-version"]
        constraints = [models.UniqueConstraint(fields=["lead", "version"], name="uniq_lead_quote_version")]

    @property
    def total(self):
        return sum(line.qty * line.price for line in self.lines.all())


class LeadQuoteLine(models.Model):
    VISIT, LABOUR, PART, PRODUCT = "visit", "labour", "part", "product"
    KIND_CHOICES = [(VISIT, "Visit charge"), (LABOUR, "Labour / service"), (PART, "Spare part"), (PRODUCT, "Product")]

    quote = models.ForeignKey(LeadQuote, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    description = models.CharField(max_length=160)
    qty = models.PositiveIntegerField(default=1)
    price = models.PositiveIntegerField()
    part = models.ForeignKey(Part, on_delete=models.PROTECT, null=True, blank=True, related_name="lead_lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, null=True, blank=True, related_name="lead_lines")
    deducted = models.BooleanField(default=False, help_text="Stock has been taken off the shelf for this line.")
    custody_qty = models.PositiveIntegerField(default=0, help_text="Of the quantity, how much came from the technician's issued stock (not the shelf).")

    class Meta:
        ordering = ["id"]


class LeadApproval(models.Model):
    PENDING, APPROVED, REJECTED, EXPIRED, REVOKED = "pending", "approved", "rejected", "expired", "revoked"
    CHANGES_REQUESTED = "changes_requested"
    CUSTOMER, ADMIN, SUPERADMIN = "customer", "admin", "superadmin"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="approvals")
    quote = models.ForeignKey(LeadQuote, on_delete=models.CASCADE, related_name="approvals")
    # 20, not 10: "changes_requested" (17 chars) must fit on PostgreSQL.
    status = models.CharField(max_length=20, default=PENDING)
    token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=12, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_ip = models.GenericIPAddressField(null=True, blank=True)
    decided_user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["lead"], condition=models.Q(status="pending"), name="uniq_lead_pending_approval"),
            models.UniqueConstraint(fields=["lead"], condition=models.Q(status="approved"), name="uniq_lead_approved_approval"),
        ]


class LeadEvent(models.Model):
    """Timeline of everything that happened on a lead."""
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=30)
    text = models.CharField(max_length=300, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class LeadPartIssue(models.Model):
    """
    Stock handed to a field technician for one job. It comes off the store's
    shelf the moment it is issued (no invoice), and stays on the books in the
    technician's name until it is used -- the work being billed -- or
    returned to the store. issued = used + returned + still with the technician.
    """
    PART, PRODUCT = "part", "product"
    KIND_CHOICES = [(PART, "Spare part"), (PRODUCT, "Product")]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="part_issues")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="part_issues")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    part = models.ForeignKey(Part, on_delete=models.PROTECT, null=True, blank=True, related_name="lead_issues")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, null=True, blank=True, related_name="lead_issues")
    description = models.CharField(max_length=160)
    qty_issued = models.PositiveIntegerField()
    qty_used = models.PositiveIntegerField(default=0)
    qty_returned = models.PositiveIntegerField(default=0)
    qty_written_off = models.PositiveIntegerField(default=0, help_text="Lost or damaged; never comes back to the shelf.")
    note = models.CharField(max_length=200, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    issued_at = models.DateTimeField(auto_now_add=True)
    alerted_at = models.DateTimeField(null=True, blank=True, help_text="When the technician was told to return the leftover.")

    class Meta:
        ordering = ["issued_at", "id"]
        constraints = [
            models.CheckConstraint(check=models.Q(qty_used__gte=0, qty_returned__gte=0), name="leadpartissue_nonneg"),
        ]

    @property
    def outstanding(self):
        return self.qty_issued - self.qty_used - self.qty_returned - self.qty_written_off

    @property
    def key(self):
        return (self.kind, self.part_id or self.variant_id)
