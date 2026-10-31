import uuid

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
    # Set when the entry is an expense paid in cash (accounting.expenses), or
    # the reversal of one when the expense was cancelled.
    expense_payment = models.OneToOneField(
        "accounting.ExpensePayment", on_delete=models.PROTECT, null=True, blank=True, related_name="cash_entry",
    )
    expense_reversal = models.OneToOneField(
        "accounting.ExpensePayment", on_delete=models.PROTECT, null=True, blank=True, related_name="cash_reversal",
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
    expense_payment = models.OneToOneField(
        "accounting.ExpensePayment", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_entry",
    )
    expense_reversal = models.OneToOneField(
        "accounting.ExpensePayment", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_reversal",
    )

    class Meta:
        ordering = ["date", "id"]
        verbose_name_plural = "bank entries"


# --------------------------------------------------------------------------
# Expenses (accounting.expenses). Amounts are whole rupees, like every
# other ledger amount, so a payment posts into the cash / bank book as is.
# --------------------------------------------------------------------------

class ExpenseCategory(models.Model):
    """What an expense was for. `classification` decides where it lands in a
    store's Profit & Loss: operating expenses, or other expenses. New
    categories are added in Django admin (Owner / superuser)."""
    OPERATING, OTHER = "operating", "other"
    CLASSIFICATION_CHOICES = [(OPERATING, "Operating expense"), (OTHER, "Other expense")]

    slug = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80, unique=True)
    classification = models.CharField(max_length=10, choices=CLASSIFICATION_CHOICES, default=OPERATING)
    is_active = models.BooleanField(default=True, help_text="Inactive categories stay on old expenses but can't be chosen for new ones.")

    class Meta:
        ordering = ["label"]
        verbose_name_plural = "expense categories"

    def __str__(self):
        return self.label


class ExpenseBatch(models.Model):
    """One bulk submission of the expense form. The browser sends a fresh
    key per form; the same key from the same account again (a double click,
    a retried request) returns the first result instead of saving twice."""
    key = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_batches")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["created_by", "key"], name="expense_batch_once_per_key")]

    def __str__(self):
        return f"Expense batch {self.key}"


class Expense(models.Model):
    """
    A cost the business incurred. Recognised in Profit & Loss on
    `expense_date` (the store's, or shared / head-office when stock_point is
    empty); payments are separate rows (ExpensePayment), each posted once to
    the cash or bank book on its own date. `paid_amount` / `payment_status`
    are kept by accounting.expenses only. Expenses are cancelled, never
    deleted, so history and posted entries stay intact.
    """
    UNPAID, PARTIAL, PAID = "unpaid", "partial", "paid"
    PAYMENT_STATUS_CHOICES = [(UNPAID, "Unpaid"), (PARTIAL, "Partly paid"), (PAID, "Paid")]
    ACTIVE, CANCELLED = "active", "cancelled"
    STATUS_CHOICES = [(ACTIVE, "Active"), (CANCELLED, "Cancelled")]

    batch = models.ForeignKey(ExpenseBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="expenses")
    # Empty = a shared / head-office cost, never assigned to one store.
    stock_point = models.ForeignKey(
        "catalog.StockPoint", on_delete=models.PROTECT, null=True, blank=True, related_name="expenses",
    )
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    expense_date = models.DateField(db_index=True, help_text="When the cost was incurred -- decides the P&L period.")
    amount = models.PositiveIntegerField(help_text="Bill total in rupees, including any GST.")
    # GST as printed on the bill -- entered, never calculated. Claimable input
    # GST is recovered, so it is left out of the expense in Profit & Loss.
    gst_amount = models.PositiveIntegerField(default=0)
    gst_claimable = models.BooleanField(default=False)
    vendor = models.CharField(max_length=120, blank=True)
    reference = models.CharField(max_length=80, blank=True, help_text="Bill / invoice number from the vendor.")
    description = models.TextField(blank=True)
    paid_amount = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=UNPAID)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_expenses",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-id"]
        indexes = [models.Index(fields=["stock_point", "expense_date"], name="expense_store_date")]
        constraints = [
            models.CheckConstraint(condition=models.Q(gst_amount__lte=models.F("amount")), name="expense_gst_within_amount"),
            models.CheckConstraint(condition=models.Q(paid_amount__lte=models.F("amount")), name="expense_paid_within_amount"),
        ]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"EXP-{self.pk:05d}" if self.pk else "EXP-new"

    @property
    def recognised_amount(self):
        """What Profit & Loss counts: the bill less claimable input GST."""
        return self.amount - (self.gst_amount if self.gst_claimable else 0)

    @property
    def outstanding(self):
        return 0 if self.status == self.CANCELLED else self.amount - self.paid_amount


class ExpensePayment(models.Model):
    """Money paid out on an expense: one cash-book or bank-book "out" entry
    (linked below), never edited. Cancelling the expense posts a reversing
    "in" entry and stamps reversed_at; the original stays as it was."""
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="payments")
    amount = models.PositiveIntegerField()
    paid_on = models.DateField()
    method = models.CharField(max_length=40)
    reference = models.CharField(max_length=80, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["paid_on", "id"]

    def __str__(self):
        return f"Payment of {self.amount} on {self.expense.code}"


def expense_attachment_path(instance, filename):
    """A random name with the extension of the type the bytes were checked
    to be -- the client's filename and path are never used on disk."""
    from django.utils import timezone

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}[instance.content_type]
    return f"expense-attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class ExpenseAttachment(models.Model):
    """A bill / receipt (JPG, PNG or PDF) of one expense. Stored under
    MEDIA_ROOT, which has no public URL: it's streamed only to accounts
    allowed to see the expense (accounting.expense_views)."""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=expense_attachment_path, max_length=255)
    original_name = models.CharField(max_length=150, help_text="Shown to people only; never used as a path.")
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_attachments")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return self.original_name
