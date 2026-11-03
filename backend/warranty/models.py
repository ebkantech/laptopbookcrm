from datetime import date

from django.db import models

from parties.models import Party
from repairs.models import RepairTicket
from sales.models import Invoice


class Warranty(models.Model):
    """
    A warranty record always names the customer AND exactly which
    part of the business granted it -- a straight product purchase
    (Sales), a completed repair job (Repair), or a rented unit
    (Rental). Sales and Repair warranties are only ever raised
    against a specific, already-completed transaction (see the
    eligibility check in the serializer/view), so there's no way to
    grant a warranty for something that was never actually delivered
    or paid for.
    """
    SALES, REPAIR, RENTAL, OTHER = "Sales", "Repair", "Rental", "Other"
    SECTION_CHOICES = [(SALES, "Sales"), (REPAIR, "Repair"), (RENTAL, "Rental"), (OTHER, "Other")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="warranties")
    section = models.CharField(max_length=10, choices=SECTION_CHOICES)
    item_label = models.CharField(max_length=160, help_text="What the warranty actually covers, e.g. 'Dell Latitude 5420' or 'Screen replacement'.")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="warranties")
    repair_ticket = models.ForeignKey(RepairTicket, on_delete=models.SET_NULL, null=True, blank=True, related_name="warranties")
    start_date = models.DateField()
    end_date = models.DateField()
    notes = models.TextField(blank=True)
    auto_created = models.BooleanField(default=False, help_text="Created by the system when the sale was paid / the repair delivered.")
    reminded_30_at = models.DateTimeField(null=True, blank=True)
    reminded_7_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-end_date"]

    def __str__(self):
        return f"{self.party.name} -- {self.item_label}"

    @property
    def status(self) -> str:
        today = date.today()
        if today > self.end_date:
            return "Expired"
        if (self.end_date - today).days <= 30:
            return "Expiring soon"
        return "Active"

    @property
    def terms_text(self) -> str:
        """
        Standard terms & conditions text for this warranty, templated
        by section. This is what prints alongside the invoice and gets
        emailed to the customer -- see warranty.serializers for where
        it's sent.
        """
        duration_days = (self.end_date - self.start_date).days
        common_tail = (
            "This warranty is void if damage results from misuse, unauthorised repair, "
            "liquid exposure, or physical damage not caused by a manufacturing or "
            "workmanship defect. Proof of purchase / this warranty record is required "
            "for any claim."
        )
        if self.section == self.SALES:
            body = (
                f"Vantage Computers warrants {self.item_label} against manufacturing "
                f"defects in materials and workmanship for {duration_days} days from the "
                f"date of purchase ({self.start_date:%d %b %Y}). During this period, "
                "defective parts will be repaired or replaced at no additional cost."
            )
        elif self.section == self.REPAIR:
            body = (
                f"Vantage Computers warrants the work performed under {self.item_label} "
                f"for {duration_days} days from the date of delivery ({self.start_date:%d %b %Y}). "
                "This covers the specific part(s) replaced and the labour performed; it "
                "does not extend to unrelated faults."
            )
        elif self.section == self.RENTAL:
            body = (
                f"For the duration of the rental agreement, Vantage Computers covers "
                f"{self.item_label} against hardware failure not caused by misuse, at no "
                "additional cost to the client, from "
                f"{self.start_date:%d %b %Y} to {self.end_date:%d %b %Y}."
            )
        else:
            body = (
                f"Vantage Computers extends the following coverage: {self.item_label}, "
                f"valid from {self.start_date:%d %b %Y} to {self.end_date:%d %b %Y}."
            )
        if self.notes:
            body += f" {self.notes}"
        return f"{body} {common_tail}"


class WarrantyClaim(models.Model):
    """A customer coming back under warranty: what went wrong, whether it was
    accepted, how it was settled and what it cost the business."""
    OPEN, APPROVED, REJECTED, RESOLVED = "open", "approved", "rejected", "resolved"
    STATUS_CHOICES = [(OPEN, "Open"), (APPROVED, "Approved"), (REJECTED, "Rejected"), (RESOLVED, "Resolved")]
    REPAIRED, REPLACED, REFUNDED, OTHER = "repaired", "replaced", "refunded", "other"
    RESOLUTION_CHOICES = [(REPAIRED, "Repaired"), (REPLACED, "Replaced"), (REFUNDED, "Refunded"), (OTHER, "Other")]

    code = models.CharField(max_length=20, unique=True)
    warranty = models.ForeignKey(Warranty, on_delete=models.CASCADE, related_name="claims")
    issue = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    repair_ticket = models.ForeignKey(RepairTicket, on_delete=models.SET_NULL, null=True, blank=True, related_name="warranty_claims",
                                      help_text="The repair job that handled this claim, if any.")
    decision_note = models.CharField(max_length=300, blank=True)
    resolution = models.CharField(max_length=10, choices=RESOLUTION_CHOICES, blank=True)
    resolution_note = models.CharField(max_length=300, blank=True)
    cost = models.PositiveIntegerField(default=0, help_text="What this claim cost the business (parts, replacement, refund).")
    raised_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, related_name="+")
    decided_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.code
