"""
Adds repairs.book: book a repair ticket, raise the bill, reopen and edit
tickets. Held by the Owner (Super Admin) and Admin ("manager") roles -- and any
role that can already assign repair jobs. Repair staff keep repairs.manage:
they receive a job, do it, move it along and send it back; they can't book,
bill or deliver.
"""
from django.db import migrations

CODENAME = "repairs.book"
DESCRIPTION = "Book repair tickets, raise the bill, reopen and edit tickets (Admin / Super Admin)"


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, defaults={"description": DESCRIPTION})
    for role in Role.objects.filter(permissions__codename="repairs.assign").distinct():
        role.permissions.add(perm)
    for role in Role.objects.filter(slug__in=("owner", "manager")):
        role.permissions.add(perm)


def remove(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_repairs_assign_permission")]
    operations = [migrations.RunPython(add, remove)]
