from django.db import migrations


def undeliver_unpaid(apps, schema_editor):
    """
    A repair is only Delivered once its invoice is paid. Tickets that
    were marked Delivered the moment their invoice was raised, while that
    invoice is still unpaid, go back to Ready for pickup; paying the
    invoice in Sales & Invoices delivers them.
    """
    RepairTicket = apps.get_model("repairs", "RepairTicket")
    Invoice = apps.get_model("sales", "Invoice")
    unpaid_ticket_ids = (
        Invoice.objects.filter(source="repair", repair_ticket__isnull=False)
        .exclude(status="Paid").values_list("repair_ticket_id", flat=True)
    )
    RepairTicket.objects.filter(pk__in=list(unpaid_ticket_ids), status="Delivered").update(status="Ready for pickup")


class Migration(migrations.Migration):
    dependencies = [
        ("repairs", "0007_delete_repairinvoice"),
        ("sales", "0006_move_repair_invoices"),
    ]

    operations = [migrations.RunPython(undeliver_unpaid, migrations.RunPython.noop)]
