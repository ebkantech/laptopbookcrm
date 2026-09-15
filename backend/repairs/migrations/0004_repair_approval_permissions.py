from django.db import migrations


REPAIR_ADMIN_PERMISSIONS = {
    "repairs.view": "View repair tickets",
    "repairs.manage": "Create tickets, finalize estimates, update stages, and settle repair bills",
    "repairs.approve": "Approve a final repair estimate on behalf of a customer",
}


def ensure_repair_admin_role_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    admin_role, _ = Role.objects.update_or_create(slug="admin", defaults={"label": "Admin"})
    permissions = []
    for codename, description in REPAIR_ADMIN_PERMISSIONS.items():
        permission, _ = Permission.objects.update_or_create(codename=codename, defaults={"description": description})
        permissions.append(permission)
    admin_role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("repairs", "0003_repair_customer_approval")]
    operations = [migrations.RunPython(ensure_repair_admin_role_permissions, migrations.RunPython.noop)]
