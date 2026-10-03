from django.db import migrations


class Migration(migrations.Migration):
    """Repair bills now live in the shared sales.Invoice ledger -- their
    rows were copied over by sales 0006 before this table is dropped."""

    dependencies = [
        ("repairs", "0006_alter_repairticketevent_event_type"),
        ("sales", "0006_move_repair_invoices"),
    ]

    operations = [
        migrations.DeleteModel(name="RepairInvoice"),
    ]
