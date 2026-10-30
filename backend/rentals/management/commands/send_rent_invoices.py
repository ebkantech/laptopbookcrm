from django.core.management.base import BaseCommand

from rentals.billing import send_due_rent_invoices


class Command(BaseCommand):
    help = "Raise and send the rent invoices falling due (recurring rental payments). Safe to run daily."

    def handle(self, *args, **options):
        result = send_due_rent_invoices()
        self.stdout.write(f"Rent invoices raised: {len(result['raised'])} {result['raised']}")
        for label, reason in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Skipped {label}: {reason}"))
