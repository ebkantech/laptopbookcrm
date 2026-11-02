"""
Adds repairs.assign: give a repair job to a staff member and step in when they
are away. Owner (Super Admin) and Admin ("manager") roles get it where they
exist. An Admin can only give jobs to staff of their own store; the Super
Admin can give a job to staff of any store.
"""
from django.db import migrations

CODENAME = "repairs.assign"
DESCRIPTION = "Give repair jobs to staff and step in on a job (Admin: own store's staff; Super Admin: any)"


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, defaults={"description": DESCRIPTION})
    for role in Role.objects.filter(slug__in=("owner", "manager")):
        role.permissions.add(perm)


def remove(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_leads_permissions")]
    operations = [migrations.RunPython(add, remove)]
