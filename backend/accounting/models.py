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

    class Meta:
        ordering = ["date", "id"]
        verbose_name_plural = "cash entries"

    def __str__(self):
        return f"{self.date} -- {self.particulars}"


class BankAccount(models.Model):
    name = models.CharField(max_length=120)
    opening = models.PositiveIntegerField(default=0)

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

    class Meta:
        ordering = ["date", "id"]
        verbose_name_plural = "bank entries"
