"""
Read-only: show exactly what role and permissions a staff account has in THIS
database, and which roles exist. Usage:  python manage.py check_access naina.joshi
Changes nothing.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User

APPS = {
    "Inventory": "inventory.edit", "Repairs & Service": "repairs.view", "Warranty": "warranty.manage",
    "Accounting": "cashbook.view", "Broadcast": "broadcast.send", "Sales & Invoices": "invoices.view",
    "Reports": "reports.view", "Dashboard": "dashboard.view", "Store Locator": "storelocator.view",
}


class Command(BaseCommand):
    help = "Print a staff account's role, store and app access (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **opts):
        u = User.objects.select_related("role", "stock_point").filter(username__iexact=opts["username"]).first()
        if not u:
            raise CommandError("No such username. Accounts that look similar: " + ", ".join(
                User.objects.filter(username__icontains=opts["username"][:4]).values_list("username", flat=True)))
        self.stdout.write(f"User: {u.username} (id {u.pk})  active={u.is_active}  superuser={u.is_superuser}")
        self.stdout.write(f"Role: {u.role.label if u.role else None}  (slug={u.role.slug if u.role else None})")
        self.stdout.write(f"Store: {u.stock_point}")
        for name, code in APPS.items():
            self.stdout.write(f"  {name:18} {code:20} {'YES' if u.has_perm_code(code) else 'no'}")
        self.stdout.write("\nAll roles in this database:")
        for r in Role.objects.all():
            self.stdout.write(f"  id={r.pk:<3} slug={r.slug:<18} label={r.label:<22} perms={r.permissions.count():<3} users={r.users.count()}")
