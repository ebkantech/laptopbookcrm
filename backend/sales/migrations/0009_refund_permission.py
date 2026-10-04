from django.db import migrations

CODENAME = "invoices.refund"
DESCRIPTION = "Refund paid invoices and take back returned items"
GRANTED_TO = ["owner", "manager", "accountant"]


def add_permission(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.update_or_create(codename=CODENAME, defaults={"description": DESCRIPTION})
    for role in Role.objects.filter(slug__in=GRANTED_TO):
        role.permissions.add(perm)


def remove_permission(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_notificationrule_via_inapp_and_more"),
        ("sales", "0008_refunds_and_advance"),
    ]

    operations = [migrations.RunPython(add_permission, remove_permission)]
