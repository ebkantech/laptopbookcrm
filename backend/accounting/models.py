from django.conf import settings
from django.db import models


class CashEntry(models.Model):
    IN, OUT = "in", "out"
    TYPE_CHOICES = [(IN, "Cash in"), (OUT, "Cash out")]

    date = models.DateField()
    particulars = models.CharField(max_length=160)
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    amount = models.PositiveIntegerField()
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_entries")
    # Set when the entry was posted automatically from an invoice payment
    # (accounting.posting) -- such entries mirror the invoice and can't be
    # edited or deleted here.
    invoice = models.OneToOneField(
        "sales.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="cash_entry",
    )
    # Set when the entry is a refund paid out on an invoice.
    refund = models.OneToOneField(
        "sales.Refund", on_delete=models.PROTECT, null=True, blank=True, related_name="cash_entry",
    )

    class Meta:
        ordering = ["date", "id"]
        verbose_name_plural = "cash entries"

    def __str__(self):
        return f"{self.date} -- {self.particulars}"


class BankAccount(models.Model):
    name = models.CharField(max_length=120)
    opening = models.PositiveIntegerField(default=0)
    # The account non-cash invoice payments (UPI, bank transfer, card,
    # cheque) are posted into. One business account for now.
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class BankEntry(models.Model):
    IN, OUT = "in", "out"
    TYPE_CHOICES = [(IN, "Credit"), (OUT, "Debit")]

    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField()
    particulars = models.CharField(max_length=160)
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    amount = models.PositiveIntegerField()
    reconciled = models.BooleanField(default=False)
    reference = models.CharField(max_length=80, blank=True, help_text="UTR / UPI ref / cheque no. -- what the statement shows.")
    invoice = models.OneToOneField(
        "sales.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_entry",
    )
    refund = models.OneToOneField(
        "sales.Refund", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_entry",
    )

    class Meta:
        ordering = ["date", "id"]
        verbose_name_plural = "bank entries"
