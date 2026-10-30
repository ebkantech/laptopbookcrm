"""
Adds expenses.manage (Accounting -> Expenses: record, view, edit, cancel
expenses and their attachments) and grants it to the built-in Owner, Admin
("manager") and Accounts ("accountant") roles, where they exist. It only
ever takes effect for a Superuser, an Admin-tier account or an Accounts
account (accounting.expenses.can_manage_expenses); an ordinary staff role
holding it is still refused. Remove it from a role in Settings to withdraw access.
"""
from django.db import migrations

CODENAME = "expenses.manage"
DESCRIPTION = "Record and manage expenses (Admins and Accounts only; limited to their stores)"
GRANTED_TO = ("owner", "manager", "accountant")


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
        ("accounts", "0010_profit_loss_permission"),
    ]

    operations = [
        migrations.RunPython(add_permission, remove_permission),
    ]
