"""
Expenses: the one place expenses, their payments and their attachments are
written. Views (accounting.expense_views) only parse requests and call this.

Accounting rules
  * An expense is recognised in Profit & Loss on its expense_date, at its
    store (or as shared / head-office when it has none), at its amount less
    any claimable input GST. Paying it never adds to that.
  * A payment is a separate ExpensePayment, made only when money actually
    went out (status Paid or Partly paid, or "record payment" later). Each
    posts exactly one "out" entry -- Cash to the cash book, any other method
    to the default bank account, the same split accounting.posting uses for
    invoices -- linked one-to-one so it can't post twice or be edited away.
  * Unpaid expenses post nothing.
  * Cancelling takes the expense out of Profit & Loss. Its payments are not
    edited or deleted: each gets a reversing "in" entry dated the day of the
    cancellation, so earlier books stay exactly as they were.

Who: can_manage_expenses() (role tier + expenses.manage), and which stores:
accounts.store_scope.StoreScope. Shared expenses belong to no store, so only
an account that sees every store can record or open them.
"""
import os
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from accounts.staff import is_staff_admin
from accounts.store_scope import StoreScope
from catalog.models import StockPoint
from sales.models import PAYMENT_METHODS

from .models import BankEntry, CashEntry, Expense, ExpenseAttachment, ExpenseBatch, ExpenseCategory, ExpensePayment
from .posting import default_bank_account

EXPENSES_PERM = "expenses.manage"
# Roles whose holders are "Accounts" users (seed_demo ROLES["accountant"]).
ACCOUNTS_ROLE_SLUGS = ("accountant",)

MAX_ENTRIES = getattr(settings, "EXPENSE_BULK_MAX_ENTRIES", 50)
MAX_FILE_BYTES = getattr(settings, "EXPENSE_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)
MAX_FILES_PER_EXPENSE = getattr(settings, "EXPENSE_ATTACHMENT_MAX_COUNT", 10)
MAX_FILES_PER_SUBMISSION = getattr(settings, "EXPENSE_BULK_MAX_FILES", 100)
ALLOWED_EXTENSIONS = {"image/jpeg": (".jpg", ".jpeg"), "image/png": (".png",), "application/pdf": (".pdf",)}
SUBMISSION_KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
SHARED_DETAIL = "Shared / head-office expenses aren't tied to a store, so only an account that sees every store can work with them."


class ExpenseError(Exception):
    """A rule an expense, payment or file broke; `errors` is {field: [message]}."""

    def __init__(self, errors):
        self.errors = errors if isinstance(errors, dict) else {"detail": [str(errors)]}
        super().__init__(str(self.errors))


# --------------------------------------------------------------------------
# Who may manage expenses
# --------------------------------------------------------------------------

def is_accounts_user(user):
    role = getattr(user, "role", None)
    return bool(role and role.slug in ACCOUNTS_ROLE_SLUGS)


def can_manage_expenses(user):
    """Superuser; or an Admin (Owner role / roles.manage) or Accounts user
    whose role holds expenses.manage. Nobody else -- holding the permission
    in another role is not enough, and is_staff plays no part."""
    if not user or not user.is_authenticated or hasattr(user, "customer_profile"):
        return False
    if user.is_superuser:
        return True
    return (is_staff_admin(user) or is_accounts_user(user)) and user.has_perm_code(EXPENSES_PERM)


def require_store_access(scope, stock_point_id):
    """The expense's store must be one this account reaches; None = shared."""
    if stock_point_id is None:
        if not scope.all:
            raise PermissionDenied(SHARED_DETAIL)
        return
    if not scope.allows(stock_point_id):
        raise PermissionDenied("You can only record expenses for your assigned store.")


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def sniff_type(head):
    """Content type from the file's own bytes, never the client's word."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def display_name(name):
    """The client's filename, for showing only: no path, no control characters."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or "attachment")[:150]


def check_upload(upload):
    """Returns the verified content type, or raises ExpenseError."""
    name = display_name(upload.name)
    ext = os.path.splitext(name)[1].lower()
    allowed = {e for exts in ALLOWED_EXTENSIONS.values() for e in exts}
    if ext not in allowed:
        raise ExpenseError({"attachments": [f"{name}: only JPG, JPEG, PNG or PDF files can be attached."]})
    if upload.size == 0:
        raise ExpenseError({"attachments": [f"{name} is empty."]})
    if upload.size > MAX_FILE_BYTES:
        raise ExpenseError({"attachments": [f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."]})
    content_type = sniff_type(upload.read(8))
    upload.seek(0)
    if content_type is None or ext not in ALLOWED_EXTENSIONS[content_type]:
        raise ExpenseError({"attachments": [f"{name}: the file's contents aren't a real {ext.lstrip('.').upper()} file."]})
    return content_type


def _save_attachment(expense, upload, content_type, user, saved):
    attachment = ExpenseAttachment(
        expense=expense, original_name=display_name(upload.name), content_type=content_type,
        size=upload.size, uploaded_by=user,
    )
    attachment.file = upload
    attachment.save()
    saved.append(attachment.file.name)
    return attachment


def _discard_files(names):
    """Remove files written by a transaction that then failed."""
    for name in names:
        try:
            ExpenseAttachment._meta.get_field("file").storage.delete(name)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Validation of one entry
# --------------------------------------------------------------------------

class ExpenseEntrySerializer(serializers.Serializer):
    """One expense as typed into the form (bulk entry or edit)."""
    stock_point = serializers.IntegerField(required=False, allow_null=True)
    shared = serializers.BooleanField(required=False, default=False)
    category = serializers.PrimaryKeyRelatedField(queryset=ExpenseCategory.objects.all())
    expense_date = serializers.DateField()
    amount = serializers.IntegerField(min_value=1, max_value=1_000_000_000)
    gst_amount = serializers.IntegerField(min_value=0, required=False, default=0)
    gst_claimable = serializers.BooleanField(required=False, default=False)
    vendor = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    payment_status = serializers.ChoiceField(choices=[c for c, _ in Expense.PAYMENT_STATUS_CHOICES], required=False, default=Expense.UNPAID)
    payment_method = serializers.ChoiceField(choices=PAYMENT_METHODS, required=False, allow_blank=True, default="")
    payment_date = serializers.DateField(required=False, allow_null=True, default=None)
    paid_amount = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    payment_reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")

    def validate_category(self, value):
        current = getattr(self.instance, "category_id", None)
        if not value.is_active and value.pk != current:
            raise serializers.ValidationError(f"{value.label} is no longer in use. Choose another category.")
        return value

    def validate(self, attrs):
        today = timezone.localdate()
        errors = {}
        shared = attrs.get("shared")
        if shared and attrs.get("stock_point"):
            errors["stock_point"] = ["Choose a store or mark the expense as shared, not both."]
        elif not shared and not attrs.get("stock_point"):
            errors["stock_point"] = ["Choose the store this expense belongs to, or mark it as shared / head office."]
        if attrs["expense_date"] > today:
            errors["expense_date"] = ["The expense date can't be in the future."]
        if attrs.get("gst_amount", 0) > attrs["amount"]:
            errors["gst_amount"] = ["GST can't be more than the bill amount."]

        status = attrs.get("payment_status", Expense.UNPAID)
        if status == Expense.UNPAID:
            # nothing was paid -- no payment details are kept
            attrs.update(payment_method="", payment_date=None, paid_amount=None, payment_reference="")
        else:
            if not attrs.get("payment_method"):
                errors["payment_method"] = ["Choose how it was paid."]
            if not attrs.get("payment_date"):
                errors["payment_date"] = ["Enter the date it was paid."]
            elif attrs["payment_date"] > today:
                errors["payment_date"] = ["The payment date can't be in the future."]
            if status == Expense.PAID:
                attrs["paid_amount"] = attrs["amount"]
            elif not attrs.get("paid_amount"):
                errors["paid_amount"] = ["Enter how much was paid."]
            elif attrs["paid_amount"] >= attrs["amount"]:
                errors["paid_amount"] = ["A part payment must be less than the bill amount -- choose Paid if it's settled."]
        if errors:
            raise serializers.ValidationError(errors)
        attrs["stock_point"] = None if shared else attrs.get("stock_point")
        return attrs


def _store(scope, stock_point_id):
    require_store_access(scope, stock_point_id)
    if stock_point_id is None:
        return None
    store = StockPoint.objects.filter(pk=stock_point_id).first()
    if store is None:
        raise ExpenseError({"stock_point": ["That store doesn't exist."]})
    return store


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------

def _particulars(expense, prefix="Expense"):
    who = f" -- {expense.vendor}" if expense.vendor else ""
    return f"{prefix} {expense.code} -- {expense.category.label}{who}"[:160]


def _post(payment, *, reversal=False):
    """One cash- or bank-book entry for a payment (or its reversal)."""
    expense = payment.expense
    if reversal:
        kwargs, date, kind = {"expense_reversal": payment}, timezone.localdate(), CashEntry.IN
        particulars = _particulars(expense, "Reversal of cancelled expense")
    else:
        kwargs, date, kind = {"expense_payment": payment}, payment.paid_on, CashEntry.OUT
        particulars = _particulars(expense)
    if payment.method == "Cash":
        return CashEntry.objects.create(date=date, particulars=particulars, type=kind, amount=payment.amount, by=payment.by, **kwargs)
    return BankEntry.objects.create(
        account=default_bank_account(), date=date, type=kind, amount=payment.amount,
        particulars=f"{particulars} via {payment.method}"[:160], reference=payment.reference[:80], **kwargs,
    )


def _refresh_status(expense):
    expense.payment_status = (
        Expense.UNPAID if expense.paid_amount == 0 else Expense.PAID if expense.paid_amount >= expense.amount else Expense.PARTIAL
    )


@transaction.atomic
def record_payment(expense, user, *, amount, paid_on, method, reference=""):
    expense = Expense.objects.select_for_update().select_related("category").get(pk=expense.pk)
    errors = {}
    if expense.status == Expense.CANCELLED:
        raise ExpenseError({"detail": ["This expense is cancelled -- no payment can be recorded on it."]})
    left = expense.amount - expense.paid_amount
    if left <= 0:
        raise ExpenseError({"detail": ["This expense is already paid in full."]})
    if method not in PAYMENT_METHODS:
        errors["payment_method"] = [f"Choose one of: {', '.join(PAYMENT_METHODS)}."]
    if not amount or amount <= 0:
        errors["amount"] = ["Enter the amount paid."]
    elif amount > left:
        errors["amount"] = [f"Only ₹{left} is outstanding on this expense."]
    if paid_on is None:
        errors["payment_date"] = ["Enter the date it was paid."]
    elif paid_on > timezone.localdate():
        errors["payment_date"] = ["The payment date can't be in the future."]
    if errors:
        raise ExpenseError(errors)
    payment = ExpensePayment.objects.create(
        expense=expense, amount=amount, paid_on=paid_on, method=method, reference=(reference or "").strip()[:80], by=user,
    )
    _post(payment)
    expense.paid_amount += amount
    _refresh_status(expense)
    expense.updated_by = user
    expense.save(update_fields=["paid_amount", "payment_status", "updated_by", "updated_at"])
    return payment


# --------------------------------------------------------------------------
# Bulk creation
# --------------------------------------------------------------------------

class BulkResult:
    def __init__(self, expenses, duplicate=False):
        self.expenses = expenses
        self.duplicate = duplicate


def _existing(user, key):
    batch = ExpenseBatch.objects.filter(created_by=user, key=key).first()
    return BulkResult(list(batch.expenses.order_by("id")), duplicate=True) if batch else None


def validate_entries(user, entries, files_by_entry):
    """Every entry checked on its own before anything is written.
    Returns (clean entries, {entry number: errors})."""
    scope = StoreScope(user)
    clean, problems = [], {}
    for index, raw in enumerate(entries):
        number = index + 1
        errors = {}
        data = None
        if not isinstance(raw, dict):
            problems[number] = {"detail": ["This entry couldn't be read."]}
            continue
        serializer = ExpenseEntrySerializer(data=raw)
        if serializer.is_valid():
            data = dict(serializer.validated_data)
            try:
                data["stock_point"] = _store(scope, data["stock_point"])
            except PermissionDenied as e:
                errors["stock_point"] = [str(e.detail)]
            except ExpenseError as e:
                errors.update(e.errors)
        else:
            errors.update({k: [str(m) for m in v] for k, v in serializer.errors.items()})
        uploads = files_by_entry.get(index, [])
        if len(uploads) > MAX_FILES_PER_EXPENSE:
            errors.setdefault("attachments", []).append(f"At most {MAX_FILES_PER_EXPENSE} attachments per expense.")
        checked = []
        for upload in uploads:
            try:
                checked.append((upload, check_upload(upload)))
            except ExpenseError as e:
                errors.setdefault("attachments", []).extend(e.errors["attachments"])
        if errors:
            problems[number] = errors
        else:
            clean.append((data, checked))
    return clean, problems


def create_bulk(user, key, entries, files_by_entry):
    """
    All entries or none. Validation first (no writes); then one transaction
    for every expense, payment, posting and attachment. Files written before
    a failure are removed again. A key already used by this account returns
    that submission's expenses (duplicate=True) without saving anything.
    """
    if not SUBMISSION_KEY_RE.match(key or ""):
        raise ExpenseError({"submission_key": ["The form is missing its submission key -- reload the page and try again."]})
    previous = _existing(user, key)
    if previous:
        return previous
    if not isinstance(entries, list) or not entries:
        raise ExpenseError({"entries": ["Add at least one expense."]})
    if len(entries) > MAX_ENTRIES:
        raise ExpenseError({"entries": [f"Save at most {MAX_ENTRIES} expenses at a time."]})
    stray = [i for i in files_by_entry if not 0 <= i < len(entries)]
    if stray:
        raise ExpenseError({"attachments": ["Some attachments don't belong to any entry. Reload the form and try again."]})
    if sum(len(f) for f in files_by_entry.values()) > MAX_FILES_PER_SUBMISSION:
        raise ExpenseError({"attachments": [f"Attach at most {MAX_FILES_PER_SUBMISSION} files in one submission."]})

    clean, problems = validate_entries(user, entries, files_by_entry)
    if problems:
        raise BulkValidationError(problems)

    saved_files = []
    try:
        with transaction.atomic():
            batch = ExpenseBatch.objects.create(key=key, created_by=user)
            created = []
            for position, (data, uploads) in enumerate(clean, start=1):
                created.append(_create_one(user, batch, data, uploads, saved_files))
    except IntegrityError:
        _discard_files(saved_files)
        previous = _existing(user, key)  # the same form sent twice at once
        if previous:
            return previous
        raise
    except BaseException:
        _discard_files(saved_files)
        raise
    return BulkResult(created)


class BulkValidationError(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__(f"{len(problems)} entries need attention")


def _create_one(user, batch, data, uploads, saved_files):
    expense = Expense.objects.create(
        batch=batch, stock_point=data["stock_point"], category=data["category"], expense_date=data["expense_date"],
        amount=data["amount"], gst_amount=data.get("gst_amount", 0), gst_claimable=data.get("gst_claimable", False),
        vendor=data.get("vendor", "").strip(), reference=data.get("reference", "").strip(),
        description=data.get("description", "").strip(), created_by=user, updated_by=user,
    )
    if data.get("paid_amount"):
        record_payment(expense, user, amount=data["paid_amount"], paid_on=data["payment_date"],
                       method=data["payment_method"], reference=data.get("payment_reference") or expense.reference)
    for upload, content_type in uploads:
        _save_attachment(expense, upload, content_type, user, saved_files)
    expense.refresh_from_db()
    return expense


# --------------------------------------------------------------------------
# Changes to a saved expense
# --------------------------------------------------------------------------

EDITABLE = ("category", "expense_date", "amount", "gst_amount", "gst_claimable", "vendor", "reference", "description")


@transaction.atomic
def update_expense(expense, user, payload):
    """Correct an expense's details. Payments are never changed here: the
    amount can't drop below what was already paid, and an expense with
    payments keeps its store (its book entries belong to that store)."""
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.status == Expense.CANCELLED:
        raise ExpenseError({"detail": ["A cancelled expense can't be edited."]})
    current = {
        "stock_point": expense.stock_point_id, "shared": expense.stock_point_id is None, "category": expense.category_id,
        "expense_date": expense.expense_date, "amount": expense.amount, "gst_amount": expense.gst_amount,
        "gst_claimable": expense.gst_claimable, "vendor": expense.vendor, "reference": expense.reference,
        "description": expense.description,
    }
    if "stock_point" in payload and payload.get("stock_point") and "shared" not in payload:
        current["shared"] = False
    serializer = ExpenseEntrySerializer(instance=expense, data={**current, **{k: v for k, v in payload.items() if k in current}})
    if not serializer.is_valid():
        raise ExpenseError({k: [str(m) for m in v] for k, v in serializer.errors.items()})
    data = serializer.validated_data
    scope = StoreScope(user)
    store_id = data["stock_point"]
    if store_id != expense.stock_point_id:
        if expense.payments.exists():
            raise ExpenseError({"stock_point": ["Payments on this expense are already in the books for its store. Cancel it and record it again under the right store."]})
        store = _store(scope, store_id)
        expense.stock_point = store
    if data["amount"] < expense.paid_amount:
        raise ExpenseError({"amount": [f"₹{expense.paid_amount} has already been paid on this expense, so the amount can't be less."]})
    for field in EDITABLE:
        value = data[field]
        setattr(expense, field, value.strip() if isinstance(value, str) else value)
    _refresh_status(expense)
    expense.updated_by = user
    expense.save()
    return expense


@transaction.atomic
def cancel_expense(expense, user, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ExpenseError({"reason": ["Give a reason for cancelling this expense."]})
    expense = Expense.objects.select_for_update().select_related("category").get(pk=expense.pk)
    if expense.status == Expense.CANCELLED:
        raise ExpenseError({"detail": ["This expense is already cancelled."]})
    for payment in expense.payments.select_for_update().filter(reversed_at__isnull=True):
        _post(payment, reversal=True)
        payment.reversed_at = timezone.now()
        payment.save(update_fields=["reversed_at"])
    expense.status = Expense.CANCELLED
    expense.cancel_reason = reason[:200]
    expense.cancelled_by = user
    expense.cancelled_at = timezone.now()
    expense.updated_by = user
    expense.save()
    return expense


def add_attachments(expense, user, uploads):
    if expense.status == Expense.CANCELLED:
        raise ExpenseError({"detail": ["Attachments can't be added to a cancelled expense."]})
    if not uploads:
        raise ExpenseError({"attachments": ["Choose at least one file."]})
    if expense.attachments.count() + len(uploads) > MAX_FILES_PER_EXPENSE:
        raise ExpenseError({"attachments": [f"An expense can have at most {MAX_FILES_PER_EXPENSE} attachments."]})
    checked = [(u, check_upload(u)) for u in uploads]
    saved = []
    try:
        with transaction.atomic():
            created = [_save_attachment(expense, u, ct, user, saved) for u, ct in checked]
            Expense.objects.filter(pk=expense.pk).update(updated_by=user, updated_at=timezone.now())
    except BaseException:
        _discard_files(saved)
        raise
    return created


def remove_attachment(attachment, user):
    if attachment.expense.status == Expense.CANCELLED:
        raise ExpenseError({"detail": ["Attachments of a cancelled expense are kept as they are."]})
    name = attachment.file.name
    with transaction.atomic():
        attachment.delete()
        Expense.objects.filter(pk=attachment.expense_id).update(updated_by=user, updated_at=timezone.now())
        transaction.on_commit(lambda: _discard_files([name]))
