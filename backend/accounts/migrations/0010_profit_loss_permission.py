"""
Adds the reports.profit_loss permission (store-wise Profit & Loss in Store
Locator -- reports.profit_loss) and grants it to the built-in Owner and
Admin ("manager") roles, where they exist. It only ever takes effect for an
Admin-tier account (accounts.staff.is_staff_admin); any other role holding
it still can't see Profit & Loss. Remove it from a role in Settings to
withdraw access.
"""
from django.db import migrations

CODENAME = "reports.profit_loss"
DESCRIPTION = "View store Profit & Loss (Admins only; limited to their stores)"
GRANTED_TO = ("owner", "manager")


def add_permission(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, defaults={"description": DESCRIPTION})
    for role in Role.objects.filter(slug__in=GRANTED_TO):
        role.permissions.add(perm)


def remove_permission(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_activitylog_actor_stock_point"),
    ]

    operations = [
        migrations.RunPython(add_permission, remove_permission),
    ]
