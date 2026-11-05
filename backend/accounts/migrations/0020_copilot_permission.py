"""Adds copilot.use for every existing role; take it off a role to hide Copilot from it."""
from django.db import migrations

CODENAME = "copilot.use"
DESCRIPTION = "Use the staff Copilot assistant"


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, defaults={"description": DESCRIPTION})
    for role in Role.objects.all():
        role.permissions.add(perm)


def remove(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0019_merge_multistore_and_security")]
    operations = [migrations.RunPython(add, remove)]
