from django.core.exceptions import ValidationError
from django.db import models

from . import catalog


class Package(models.Model):
    """What is sold: a named set of modules. Prices sit on PackagePrice."""
    key = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    modules = models.JSONField(default=list, help_text="Dependencies are added automatically when saved.")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        catalog.with_dependencies(self.modules)

    def save(self, *args, **kwargs):
        self.modules = catalog.with_dependencies(self.modules)
        super().save(*args, **kwargs)


class PackagePrice(models.Model):
    DURATIONS = [(1, "1 month"), (3, "3 months"), (6, "6 months"), (12, "12 months")]

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="prices")
    months = models.PositiveSmallIntegerField(choices=DURATIONS)
    amount = models.PositiveIntegerField(help_text="Whole rupees. 0 means free.")

    class Meta:
        ordering = ["months"]
        constraints = [models.UniqueConstraint(fields=["package", "months"], name="one_price_per_duration")]

    def __str__(self):
        return f"{self.package} / {self.months} months: Rs {self.amount}"


class Subscription(models.Model):
    """This installation's plan. There is one row; see services.current()."""
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="subscriptions")
    months = models.PositiveSmallIntegerField(choices=PackagePrice.DURATIONS)
    amount = models.PositiveIntegerField()
    starts_on = models.DateField()
    ends_on = models.DateField(help_text="The last paid day is the day before this.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.package} until {self.ends_on}"

    def clean(self):
        if self.ends_on <= self.starts_on:
            raise ValidationError("The end date must be after the start date.")


class SubscriptionEvent(models.Model):
    """History of plan changes and reminders. `key` stops a reminder repeating."""
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    key = models.CharField(max_length=60)
    text = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["subscription", "key"], name="one_subscription_event_per_key")]
