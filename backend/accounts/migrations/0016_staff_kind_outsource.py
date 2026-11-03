"""
Field technicians (not bound to a store) and outsourced technicians.
Adds User.staff_kind / User.company and the permission leads.outsource, which
only the Owner / Admin roles (and any role that can already approve on-site
jobs) receive -- it alone lets someone create or assign outsourced technicians.
"""
from django.db import migrations, models


def grant(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.get_or_create(
        codename="leads.outsource",
        defaults={"description": "Add outsourced technicians and give them on-site jobs (Admin / Super Admin)"},
    )
    roles = set(Role.objects.filter(slug__in=("owner", "manager")).values_list("pk", flat=True))
    roles |= set(Role.objects.filter(permissions__codename="leads.approve").values_list("pk", flat=True))
    for role in Role.objects.filter(pk__in=roles):
        role.permissions.add(perm)


def revoke(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename="leads.outsource").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_dashboard_locator_reports_permissions")]
    operations = [
        migrations.AddField("user", "staff_kind", models.CharField(
            choices=[("store", "Store staff"), ("field", "Field technician (any store)"), ("outsourced", "Outsourced technician")],
            default="store", max_length=12)),
        migrations.AddField("user", "company", models.CharField(
            blank=True, max_length=80, help_text="Partner company / freelancer name for an outsourced technician.")),
        migrations.RunPython(grant, revoke),
    ]
