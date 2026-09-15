import calendar
from datetime import date

from django.conf import settings
from django.db import models

from parties.models import Party


def add_months(d: date, months: int) -> date:
    """Calendar-correct month addition (handles Jan 31 + 1mo -> Feb 28/29, etc.)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class Rental(models.Model):
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="rentals")
    product_label = models.CharField(max_length=120, help_text="Free-text device description, e.g. 'Dell Latitude 5420'.")
    monthly_fee = models.PositiveIntegerField()
    start = models.DateField()
    tenure_months = models.PositiveIntegerField()
    months_paid = models.PositiveIntegerField(default=0)
    late_count = models.PositiveIntegerField(default=0)
    tickets = models.PositiveIntegerField(default=0, help_text="Support tickets raised during the tenure -- kept in sync with RentalIssue count.")
    last_payment = models.DateField()

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return f"{self.party.name} -- {self.product_label}"

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
