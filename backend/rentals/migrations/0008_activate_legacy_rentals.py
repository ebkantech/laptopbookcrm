from django.db import migrations


def activate_legacy_rentals(apps, schema_editor):
    """
    Same rule as 0006: rentals from before agreement workflows (no
    agreement code) are live rentals, not drafts. 0006 only fixed rows
    that existed when it ran; seed_demo kept creating new ones as drafts,
    which also kept them out of rent invoicing.
    """
    Rental = apps.get_model("rentals", "Rental")
    Rental.objects.filter(agreement_code__isnull=True, status="draft").update(status="active")


class Migration(migrations.Migration):
    dependencies = [("rentals", "0007_rentalapproval_decided_ip_and_more")]

    operations = [migrations.RunPython(activate_legacy_rentals, migrations.RunPython.noop)]
