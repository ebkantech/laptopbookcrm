from django.conf import settings
from django.db import models

from catalog.models import StockPoint, Variant
from parties.models import Party


class Invoice(models.Model):
    """
    Every invoice the business raises -- product sales, repair jobs and
    rental rent -- lives here, numbered from one INV-#### sequence
    (sales.services.next_invoice_code). The repair and rental modules run
    their own processes and *raise* invoices here; payment is recorded
    only against these rows (settle / UPI link), and
    sales.services.on_invoice_paid tells the originating module.
    """
    SALE, REPAIR, RENTAL = "sale", "repair", "rental"
    SOURCE_CHOICES = [(SALE, "Sale"), (REPAIR, "Repair"), (RENTAL, "Rental")]

    PAID, LINK_SENT, OVERDUE, CANCELLED = "Paid", "Payment link sent", "Overdue", "Cancelled"
    STATUS_CHOICES = [(PAID, "Paid"), (LINK_SENT, "Payment link sent"), (OVERDUE, "Overdue"), (CANCELLED, "Cancelled")]
    # Still owed: everything that's neither paid nor cancelled. Use this,
    # never "status != Paid", so cancelled invoices don't count as owed.
    OUTSTANDING = (LINK_SENT, OVERDUE)

    RECURRING_CHOICES = [("weekly", "Weekly"), ("monthly", "Monthly"), ("6-month", "Every 6 months")]

    code = models.CharField(max_length=20, unique=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SALE, db_index=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="invoices")
    # What the invoice was raised for (exactly one, matching `source`,
    # or none for a plain sale).
    repair_ticket = models.ForeignKey(
        "repairs.RepairTicket", on_delete=models.PROTECT, null=True, blank=True, related_name="invoices",
    )
    repair_reopen = models.OneToOneField(
        "repairs.RepairReopen", on_delete=models.PROTECT, null=True, blank=True, related_name="invoice",
        help_text="Set for the bill of a reopened (follow-up) repair visit.",
    )
    rental = models.ForeignKey(
        "rentals.Rental", on_delete=models.PROTECT, null=True, blank=True, related_name="invoices",
    )
    # Rental rent invoices: the month being billed.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="invoices")
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=LINK_SENT)
    pay_method = models.CharField(max_length=40, blank=True)
    # Recorded by staff when a payment is received (there is no payment
    # gateway wired in, so this is the audit trail for every settlement):
    # when it was paid, the UPI/UTR/cheque/card reference to match against
    # the bank statement, and who recorded it.
    # When payment is due; past it, an unpaid invoice is marked Overdue
    # (sales.services.mark_overdue). Sales/repairs: date + INVOICE_DUE_DAYS;
    # rent: the first day of the month billed.
    due_date = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=80, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_invoices",
    )
    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="settled_invoices",
    )
    recurring_interval = models.CharField(max_length=10, choices=RECURRING_CHOICES, blank=True)
    recurring_next = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.code

    @property
    def total(self):
        return sum(item.qty * item.price for item in self.items.all())


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    # Sale lines point at the stock variant sold; repair/rental lines are
    # services or rent and carry a description instead.
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="invoice_items", null=True, blank=True)
    description = models.CharField(max_length=160, blank=True)
    qty = models.PositiveIntegerField(default=1)
    # Signed so a repair bill can carry a "Less: advance received" line;
    # sale lines are validated non-negative in the serializer.
    price = models.IntegerField(help_text="Snapshot of the unit price at the time of invoicing.")

    @property
    def label(self):
        if self.description:
            return self.description
        return f"{self.variant.product.display_name} ({self.variant.spec})" if self.variant_id else ""


PAYMENT_METHODS = ["Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"]


class PaymentLink(models.Model):
    """
    One UPI payment link sent for an invoice: to which number, whether
    that number was confirmed to have UPI (and how), who sent it, and
    what came of it. See sales/payments.py for the flow.
    """
    SENT, PAID, CANCELLED, FAILED = "sent", "paid", "cancelled", "failed"
    STATUS_CHOICES = [(SENT, "Sent"), (PAID, "Paid"), (CANCELLED, "Cancelled"), (FAILED, "Failed")]
    # How the number's UPI registration was established before sending.
    UPI_VERIFIED, UPI_STAFF_CONFIRMED = "verified", "staff_confirmed"
    UPI_CHECK_CHOICES = [
        (UPI_VERIFIED, "Verified by lookup"),
        (UPI_STAFF_CONFIRMED, "Confirmed with customer by staff"),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payment_links")
    phone = models.CharField(max_length=10, help_text="10-digit Indian mobile number the link was sent to.")
    upi_check = models.CharField(max_length=20, choices=UPI_CHECK_CHOICES)
    amount = models.PositiveIntegerField(help_text="Rupees, at the time the link was sent.")
    provider = models.CharField(max_length=20)
    provider_link_id = models.CharField(max_length=64, blank=True, db_index=True)
    url = models.URLField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=SENT)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_links_sent")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_payment_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice.code} → ******{self.phone[-4:]} ({self.status})"
