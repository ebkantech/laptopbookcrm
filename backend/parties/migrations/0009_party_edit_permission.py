from django.db import migrations

CODENAME = "parties.edit"
DESCRIPTION = "Edit existing customer records"
GRANTED_TO = ["owner", "manager"]


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
        ("accounts", "0005_rental_changes_requested_alert"),
        ("parties", "0008_message_whatsapp_delivery"),
    ]

    operations = [migrations.RunPython(add_permission, remove_permission)]
