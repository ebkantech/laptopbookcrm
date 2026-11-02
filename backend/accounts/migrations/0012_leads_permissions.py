"""
Adds the on-site service (Leads) permissions. Owner and Admin ("manager")
roles get all of them where they exist; a "Field Technician" role is
created with the technician set. Remove or regrant them in Settings.
"""
from django.db import migrations

PERMS = {
    "leads.view": "View on-site service jobs (technicians see only their own)",
    "leads.create": "Create on-site service jobs",
    "leads.assign": "Assign on-site jobs to staff; see every job at the store",
    "leads.work": "Visit, diagnose and complete assigned on-site jobs",
    "leads.quote": "Prepare the bill for an on-site job",
    "leads.approve": "Approve on-site bills on behalf of the client (Admin / Super Admin)",
    "leads.collect": "Raise advances and collect payment for on-site jobs",
    "leads.manage": "Edit, reschedule, cancel and close on-site jobs",
}
ADMIN_ROLES = ("owner", "manager")
TECH = ("leads.view", "leads.work", "leads.quote", "leads.collect")


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perms = {c: Permission.objects.get_or_create(codename=c, defaults={"description": d})[0] for c, d in PERMS.items()}
    for role in Role.objects.filter(slug__in=ADMIN_ROLES):
        role.permissions.add(*perms.values())
    tech, _ = Role.objects.get_or_create(slug="field_tech", defaults={"label": "Field Technician"})
    tech.permissions.add(*[perms[c] for c in TECH])
    for role in Role.objects.filter(slug="auditor"):
        role.permissions.add(perms["leads.view"])


def remove(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename__in=list(PERMS)).delete()
    apps.get_model("accounts", "Role").objects.filter(slug="field_tech").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_expenses_permission")]
    operations = [migrations.RunPython(add, remove)]
