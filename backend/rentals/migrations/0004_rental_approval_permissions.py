from django.db import migrations


RENTAL_ADMIN_PERMISSIONS = {
    "rentals.approve": "Approve a rental agreement on behalf of a customer",
}


def ensure_rental_approval_permission(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    admin_role, _ = Role.objects.update_or_create(slug="admin", defaults={"label": "Admin"})
    for codename, description in RENTAL_ADMIN_PERMISSIONS.items():
        permission, _ = Permission.objects.update_or_create(
            codename=codename,
            defaults={"description": description},
        )
        admin_role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("rentals", "0003_rentalasset_rental_agreement_code_rental_status_and_more")]

    operations = [migrations.RunPython(ensure_rental_approval_permission, migrations.RunPython.noop)]
