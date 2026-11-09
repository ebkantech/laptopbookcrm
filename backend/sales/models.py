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
    SALE, REPAIR, RENTAL, ONSITE = "sale", "repair", "rental", "onsite"
    SOURCE_CHOICES = [(SALE, "Sale"), (REPAIR, "Repair"), (RENTAL, "Rental"), (ONSITE, "On-site service")]

    PAID, LINK_SENT, OVERDUE, CANCELLED, REFUNDED = "Paid", "Payment link sent", "Overdue", "Cancelled", "Refunded"
    STATUS_CHOICES = [
        (PAID, "Paid"), (LINK_SENT, "Payment link sent"), (OVERDUE, "Overdue"),
        (CANCELLED, "Cancelled"), (REFUNDED, "Refunded"),
    ]
    # Still owed: everything that's neither paid nor cancelled. Use this,
    # never "status != Paid", so cancelled invoices don't count as owed.
    OUTSTANDING = (LINK_SENT, OVERDUE)
    # Paid in full or part -- may carry refunds. A fully refunded invoice
    # moves to Refunded; a part-refunded one stays Paid.
    SETTLED = (PAID, REFUNDED)

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
    # A repair advance: collected up front when the ticket is booked and
    # deducted on the final repair bill (repairs.billing).
    is_advance = models.BooleanField(default=False)
    # A rental security deposit: refundable, so the customer's money rather
    # than income. Counted in the cash and bank books, never in revenue or
    # rent (rentals.onboarding).
    is_deposit = models.BooleanField(default=False)
    rental = models.ForeignKey(
        "rentals.Rental", on_delete=models.PROTECT, null=True, blank=True, related_name="invoices",
    )
    # On-site service: the lead this invoice (advance, visit charge or
    # final bill) was raised for.
    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.PROTECT, null=True, blank=True, related_name="invoices",
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
    # A discount on a whole sale. The amount itself is a negative line on the
    # invoice (InvoiceItem.DISCOUNT), so totals, payments and profit all follow it.
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_reason = models.CharField(max_length=200, blank=True)
    discount_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="discounted_invoices",
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

    @property
    def refunded_total(self):
        return sum(r.amount for r in self.refunds.all())

    @property
    def amount_paid(self):
        """Received so far: all of it once paid, otherwise the part payments."""
        if self.status in self.SETTLED:
            return self.total
        if self.status == self.CANCELLED:
            return 0
        return sum(p.amount for p in self.part_payments.all())

    @property
    def balance_due(self):
        """Still owed. Nothing on a paid or cancelled invoice."""
        if self.status not in self.OUTSTANDING:
            return 0
        return max(self.total - self.amount_paid, 0)

    @property
    def net_total(self):
        """What the business kept: the total less anything refunded.
        Revenue figures use this for paid invoices."""
        return self.total - self.refunded_total


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
    # What one unit cost the business, locked when the line is created, so a
    # later cost correction never rewrites past profit (reports.profit_loss).
    # None = no cost recorded (labour, visit charge, rent, or not entered).
    PRODUCT, PART, SERVICE, DISCOUNT = "product", "part", "service", "discount"
    unit_cost = models.PositiveIntegerField(null=True, blank=True)
    cost_estimated = models.BooleanField(default=False, help_text="unit_cost was the automatic guess, not a purchase price.")
    item_kind = models.CharField(max_length=10, blank=True, help_text="product / part: goods whose cost must be known.")
    # Printed under the line on the invoice: condition, accessories in the box, etc.
    remarks = models.CharField(max_length=300, blank=True)
    # The guarantee promised on this item, in months. Blank = none promised:
    # nothing is printed and no warranty record is made for it.
    warranty_months = models.PositiveSmallIntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.variant_id and not self.item_kind:
            self.item_kind = self.PRODUCT
        if self.variant_id and self.unit_cost is None and not self.pk:
            self.unit_cost = self.variant.cost
            self.cost_estimated = self.variant.cost_estimated
        super().save(*args, **kwargs)

    @property
    def label(self):
        if self.description:
            return self.description
        if not self.variant_id:
            return ""
        colour = f", {self.variant.colour}" if self.variant.colour else ""
        return f"{self.variant.product.display_name} ({self.variant.spec}{colour})"


PAYMENT_METHODS = ["Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"]


class InvoicePayment(models.Model):
    """
    Money received against an invoice in instalments. The invoice stays
    outstanding until they add up to its total; then it is marked paid as
    usual. Each one is posted to the cash or bank book on its own.
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="part_payments")
    amount = models.PositiveIntegerField()
    pay_method = models.CharField(max_length=40)
    payment_reference = models.CharField(max_length=80, blank=True)
    paid_on = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="invoice_payments_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paid_on", "id"]

    def __str__(self):
        return f"Rs {self.amount} on {self.invoice.code}"


class PaymentLink(models.Model):
    """
    One UPI payment link sent for an invoice: to which number, whether
    that number was confirmed to have UPI (and how), who sent it, and
    what came of it. See sales/payments.py for the flow.
    """
    SENT, PAID, CANCELLED, FAILED = "sent", "paid", "cancelled", "failed"
    STATUS_CHOICES = [(SENT, "Sent"), (PAID, "Paid"), (CANCELLED, "Cancelled"), (FAILED, "Failed")]
    # How the number's UPI registration was established before sending.
    UPI_VERIFIED, UPI_STAFF_CONFIRMED, UPI_NOT_CHECKED = "verified", "staff_confirmed", "not_checked"
    UPI_CHECK_CHOICES = [
        (UPI_VERIFIED, "Verified by lookup"),
        (UPI_STAFF_CONFIRMED, "Confirmed with customer by staff"),
        (UPI_NOT_CHECKED, "Sent automatically with the invoice"),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payment_links")
    phone = models.CharField(max_length=10, help_text="10-digit Indian mobile number the link was sent to.")
    upi_check = models.CharField(max_length=20, choices=UPI_CHECK_CHOICES)
    amount = models.PositiveIntegerField(help_text="Rupees, at the time the link was sent.")
    provider = models.CharField(max_length=20)
    provider_link_id = models.CharField(max_length=64, blank=True, db_index=True)
    url = models.URLField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=SENT)
    # Blank when the rent scheduler sent it: no person was involved.
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payment_links_sent")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_payment_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice.code} → ******{self.phone[-4:]} ({self.status})"


class Refund(models.Model):
    """
    Money paid back on a paid invoice -- a product return, or a partial
    refund (a repair/rent goodwill amount, an advance returned). A sale
    refund names the lines and quantities returned; those units can go
    back on the shelf. Posted out of the cash or bank book
    (accounting.posting.post_refund).
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="refunds")
    amount = models.PositiveIntegerField()
    method = models.CharField(max_length=40)
    reference = models.CharField(max_length=80, blank=True)
    reason = models.CharField(max_length=200)
    refunded_on = models.DateField()
    restocked = models.BooleanField(default=False, help_text="Returned units were put back into stock.")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="refunds_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Refund of {self.amount} on {self.invoice.code}"


class RefundItem(models.Model):
    refund = models.ForeignKey(Refund, on_delete=models.CASCADE, related_name="items")
    invoice_item = models.ForeignKey(InvoiceItem, on_delete=models.PROTECT, related_name="refund_items")
    qty = models.PositiveIntegerField()
