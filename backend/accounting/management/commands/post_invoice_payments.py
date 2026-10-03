from django.core.management.base import BaseCommand

from accounting.posting import post_invoice_payment
from sales.models import Invoice


class Command(BaseCommand):
    help = (
        "Post invoice payments recorded before automatic posting existed into the cash/bank books. "
        "Safe to re-run: invoices already posted are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would be posted without writing anything.")

    def handle(self, *args, **options):
        posted = 0
        for invoice in Invoice.objects.filter(status=Invoice.PAID).select_related("party", "settled_by").prefetch_related("items").order_by("paid_on", "date", "id"):
            if hasattr(invoice, "cash_entry") or hasattr(invoice, "bank_entry"):
                continue
            if invoice.total <= 0 or invoice.pay_method == "No charge":
                continue
            book = "cash" if invoice.pay_method == "Cash" else "bank"
            self.stdout.write(f"{invoice.code}  Rs {invoice.total:>9}  {invoice.pay_method or '(method not recorded)':<22} -> {book} book")
            if not options["dry_run"]:
                post_invoice_payment(invoice)
            posted += 1
        verb = "Would post" if options["dry_run"] else "Posted"
        self.stdout.write(self.style.SUCCESS(f"{verb} {posted} payment(s)."))
