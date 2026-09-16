from django.db import migrations


PERMISSIONS = {
    "rentals.view": "View rental assets",
    "rentals.approve": "Approve rental agreements on behalf of customers",
}

ROLE_PERMISSIONS = {
    "owner": ("Owner", ("rentals.view", "rentals.approve")),
    "admin": ("Admin", ("rentals.view", "rentals.approve")),
    "manager": ("Store Manager", ("rentals.view",)),
}


def reconcile_data(apps, schema_editor):
    Rental = apps.get_model("rentals", "Rental")
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    # Rows created before agreement workflows were introduced represent live
    # rentals, not drafts waiting for approval.
    Rental.objects.filter(agreement_code__isnull=True, status="draft").update(status="active")

    permissions = {
        codename: Permission.objects.update_or_create(
            codename=codename,
            defaults={"description": description},
        )[0]
        for codename, description in PERMISSIONS.items()
    }
    for slug, (label, codenames) in ROLE_PERMISSIONS.items():
        role, _ = Role.objects.update_or_create(slug=slug, defaults={"label": label})
        role.permissions.add(*(permissions[codename] for codename in codenames))


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("rentals", "0005_alter_rental_status_alter_rentalevent_event_type"),
    ]

    operations = [migrations.RunPython(reconcile_data, migrations.RunPython.noop)]
