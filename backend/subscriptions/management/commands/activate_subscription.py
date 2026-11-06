from django.core.management.base import BaseCommand, CommandError

from subscriptions import services
from subscriptions.models import PackagePrice


class Command(BaseCommand):
    help = "Start or renew the plan: activate_subscription <package key> <months>. Run by the vendor after payment."

    def add_arguments(self, parser):
        parser.add_argument("package", help="starter, service, rental or full")
        parser.add_argument("months", type=int, help="1, 3, 6 or 12")

    def handle(self, *args, **options):
        try:
            row = services.activate(options["package"], options["months"])
        except PackagePrice.DoesNotExist:
            raise CommandError("No such package and duration. Packages: starter, service, rental, full. Months: 1, 3, 6, 12.")
        self.stdout.write(f"{row.package.name} active until {row.ends_on} (Rs {row.amount}).")
