"""
Adds dashboard.view, storelocator.view and reports.view so the Dashboard, Store
Locator and Reports apps are opened by permission like every other app (until
now every staff account saw them). Existing office roles keep them: the Owner
and Admin roles, and any role that already handles sales, accounting or
reports. Work-only roles such as repair staff do not get them -- an Admin or
Super Admin switches them on per role in Settings -> Roles & access.
"""
from django.db import migrations

PERMS = {
    "dashboard.view": "Open the Dashboard overview",
    "storelocator.view": "Open the Store Locator (stores, channels and their stock)",
    "reports.view": "Open the Reports app (each report still needs its own permission)",
}
OFFICE_MARKERS = ["invoices.view", "cashbook.view", "bankbook.view", "reports.export", "roles.manage", "parties.manage", "inventory.edit"]


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perms = {code: Permission.objects.get_or_create(codename=code, defaults={"description": d})[0] for code, d in PERMS.items()}
    office = set(Role.objects.filter(permissions__codename__in=OFFICE_MARKERS).values_list("pk", flat=True))
    office |= set(Role.objects.filter(slug__in=("owner", "manager")).values_list("pk", flat=True))
    for role in Role.objects.filter(pk__in=office):
        for perm in perms.values():
            role.permissions.add(perm)


def remove(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename__in=list(PERMS)).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_repairs_book_permission")]
    operations = [migrations.RunPython(add, remove)]
