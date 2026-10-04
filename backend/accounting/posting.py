"""
Invoice payments flow into the books automatically. Every route that
marks an invoice paid ends in sales.services.on_invoice_paid(), which
calls post_invoice_payment():

  Cash                                   -> cash book, "in"
  UPI / Bank transfer / Card / Cheque /
  Other                                  -> bank book of the default
                                            account, "in", unreconciled
  No charge (nothing collected)          -> nothing

Refunds (sales.services.refund_invoice) go the other way through
post_refund(): cash refunds out of the cash book, anything else out of
the default bank account.

Each posted entry is linked to its invoice (one entry per invoice), so
posting is idempotent and the entry can't be edited away from the
invoice it mirrors.
"""
from django.db import transaction

from .models import BankAccount, BankEntry, CashEntry

NO_MONEY_METHODS = {"No charge"}


def default_bank_account():
    """The business bank account; created on first use so a payment is
    never left unposted (rename it and set its opening balance in
    Accounting > Bank book)."""
    account = BankAccount.objects.filter(is_default=True).first() or BankAccount.objects.order_by("id").first()
    if account is None:
        return BankAccount.objects.create(name="Business bank account", opening=0, is_default=True)
    if not account.is_default:
        account.is_default = True
        account.save(update_fields=["is_default"])
    return account


def _particulars(invoice):
    what = {"sale": "Sale", "repair": "Repair", "rental": "Rent"}.get(invoice.source, "Invoice")
    return f"{what} {invoice.code} -- {invoice.party.name}"[:160]


@transaction.atomic
def post_invoice_payment(invoice):
    """Post a just-paid invoice to the cash or bank book. Returns the entry,
    or None when nothing was collected or it's already posted."""
    if invoice.total <= 0 or invoice.pay_method in NO_MONEY_METHODS:
        return None
    if CashEntry.objects.filter(invoice=invoice).exists() or BankEntry.objects.filter(invoice=invoice).exists():
        return None
    date = invoice.paid_on or invoice.date
    if invoice.pay_method == "Cash":
        by = invoice.settled_by
        if by is None:  # cash is always recorded by a person; fall back defensively
            from accounts.models import User

            by = User.objects.filter(is_superuser=True).order_by("id").first()
        particulars = _particulars(invoice)
        if invoice.payment_reference:
            particulars = f"{particulars} (receipt {invoice.payment_reference})"[:160]
        return CashEntry.objects.create(
            date=date, particulars=particulars, type=CashEntry.IN, amount=invoice.total, by=by, invoice=invoice,
        )
    return BankEntry.objects.create(
        account=default_bank_account(), date=date, type=BankEntry.IN, amount=invoice.total,
        particulars=f"{_particulars(invoice)} via {invoice.pay_method or 'bank'}"[:160],
        reference=invoice.payment_reference[:80], invoice=invoice,
    )


@transaction.atomic
def post_refund(refund):
    """Post money paid back on an invoice as an "out" entry."""
    if CashEntry.objects.filter(refund=refund).exists() or BankEntry.objects.filter(refund=refund).exists():
        return None
    invoice = refund.invoice
    particulars = f"Refund on {_particulars(invoice)}"
    if refund.method == "Cash":
        return CashEntry.objects.create(
            date=refund.refunded_on, particulars=particulars[:160], type=CashEntry.OUT,
            amount=refund.amount, by=refund.by, refund=refund,
        )
    return BankEntry.objects.create(
        account=default_bank_account(), date=refund.refunded_on, type=BankEntry.OUT, amount=refund.amount,
        particulars=f"{particulars} via {refund.method}"[:160], reference=refund.reference[:80], refund=refund,
    )
