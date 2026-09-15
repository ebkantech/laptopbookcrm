from django.db import models

from catalog.models import StockPoint, Variant
from parties.models import Party


class Invoice(models.Model):
    PAID, LINK_SENT, OVERDUE = "Paid", "Payment link sent", "Overdue"
    STATUS_CHOICES = [(PAID, "Paid"), (LINK_SENT, "Payment link sent"), (OVERDUE, "Overdue")]

    RECURRING_CHOICES = [("weekly", "Weekly"), ("monthly", "Monthly"), ("6-month", "Every 6 months")]

    code = models.CharField(max_length=20, unique=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="invoices")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="invoices")
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=LINK_SENT)
    pay_method = models.CharField(max_length=40, blank=True)
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
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="invoice_items")
    qty = models.PositiveIntegerField(default=1)
    price = models.PositiveIntegerField(help_text="Snapshot of sell price at the time of sale.")
