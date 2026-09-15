from django.db import models

from catalog.models import Service, StockPoint
from parties.models import Party


class RepairTicket(models.Model):
    RECEIVED, DIAGNOSING, IN_PROGRESS, READY, DELIVERED = (
        "Received", "Diagnosing", "In progress", "Ready for pickup", "Delivered",
    )
    STAGES = [RECEIVED, DIAGNOSING, IN_PROGRESS, READY, DELIVERED]
    STATUS_CHOICES = [(s, s) for s in STAGES]

    ADVANCE, FULL = "advance", "full"
    PAYMENT_CHOICES = [(ADVANCE, "25% advance"), (FULL, "Pay on delivery")]

    code = models.CharField(max_length=20, unique=True)
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
        return sum(s.charge for s in self.services.all())

    @property
    def balance_due(self):
        return self.total - self.advance_paid

    def next_stage(self):
        idx = self.STAGES.index(self.status)
        return self.STAGES[idx + 1] if idx + 1 < len(self.STAGES) else None

    @property
    def original_invoice(self):
        return self.invoices.filter(reopen__isnull=True).first()

    @property
    def active_reopen(self):
        """The most recent reopen that hasn't been settled yet, if any."""
        return self.reopens.filter(invoice__isnull=True).first()


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
