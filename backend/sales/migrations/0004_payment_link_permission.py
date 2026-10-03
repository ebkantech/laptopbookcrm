from django.db import migrations

CODENAME = "payments.send_link"
DESCRIPTION = "Send UPI payment links to customers"
# Repair Staff deliberately excluded -- they never send payment links.
GRANTED_TO = ["owner", "manager", "sales", "accountant"]


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
        ("sales", "0003_payment_link"),
    ]

    operations = [migrations.RunPython(add_permission, remove_permission)]
