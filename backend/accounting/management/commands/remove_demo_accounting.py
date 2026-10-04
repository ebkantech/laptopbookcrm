"""
Remove the sample cash/bank entries seed_demo put in the books, so the
cash and bank books show only real money: invoice payments, refunds and
entries staff added themselves.

Only rows that exactly match the seeded samples (date, particulars,
amount, and not linked to an invoice) are deleted; the seeded bank
account is kept -- payments are posted into it -- but renamed and its
sample opening balance reset to 0. Set the real name and opening
balance afterwards in Accounting > Bank book.

    python manage.py remove_demo_accounting --dry-run   # show what would go
    python manage.py remove_demo_accounting
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import BankAccount, BankEntry, CashEntry

DEMO_CASH = [
    (date(2026, 9, 1), "Opening balance", 42000),
    (date(2026, 9, 2), "Cash sale, Karol Bagh", 18500),
]
DEMO_BANK = [
    (date(2026, 9, 1), "Opening balance", 612000),
    (date(2026, 9, 3), "NEFT — Bright Minds School", 209994),
]
DEMO_ACCOUNT = ("HDFC Bank — Current A/c ••4821", 612000)


class Command(BaseCommand):
    help = "Delete the sample cash and bank entries created by seed_demo."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would be removed without removing it.")

    @transaction.atomic
    def handle(self, *args, dry_run=False, **options):
        doomed = []
        for model, rows in ((CashEntry, DEMO_CASH), (BankEntry, DEMO_BANK)):
            for day, particulars, amount in rows:
                doomed += list(model.objects.filter(
                    date=day, particulars=particulars, amount=amount, invoice__isnull=True, refund__isnull=True,
                ))
        accounts = list(BankAccount.objects.filter(name=DEMO_ACCOUNT[0], opening=DEMO_ACCOUNT[1]))

        for entry in doomed:
            book = "cash" if isinstance(entry, CashEntry) else "bank"
            self.stdout.write(f"  {book} book: {entry.date} {entry.particulars} -- Rs {entry.amount}")
        for account in accounts:
            self.stdout.write(f"  bank account '{account.name}' -> 'Business bank account', opening 612000 -> 0")
        if not doomed and not accounts:
            self.stdout.write(self.style.SUCCESS("No demo accounting data found -- nothing to do."))
            return
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run -- nothing was changed."))
            return
        for entry in doomed:
            entry.delete()
        for account in accounts:
            account.name, account.opening = "Business bank account", 0
            account.save(update_fields=["name", "opening"])
        self.stdout.write(self.style.SUCCESS(f"Removed {len(doomed)} demo entries."))
