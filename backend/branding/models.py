"""
What the customer sees, edited in Settings -> Business & messages instead of
being fixed in code: the business's own details (letterhead of invoices,
statements and rental agreements), the fixed wording on those documents,
and every WhatsApp / SMS / email the CRM sends a customer.
"""
from django.conf import settings
from django.db import models


class BusinessProfile(models.Model):
    """One row (pk=1). A blank field falls back to the matching BUSINESS_* setting in .env."""
    name = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    website = models.CharField(max_length=120, blank=True)
    # on every invoice
    invoice_footer = models.CharField(max_length=300, blank=True)
    signatory_label = models.CharField(max_length=60, blank=True)
    invoice_notes = models.TextField(blank=True, help_text="Printed on every invoice above the signature, e.g. payment / return terms.")
    # the rental agreement's Terms and Conditions, one per line; blank = the standard ten
    rental_terms = models.TextField(blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or "Business profile"


class MessageText(models.Model):
    """The edited wording of one customer message (branding.registry key). No row = the standard wording."""
    key = models.CharField(max_length=60, unique=True)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    # for messages whose email says something different from the WhatsApp text
    email_body = models.TextField(blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key
