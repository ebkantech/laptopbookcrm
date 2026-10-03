from django.db import migrations


def move_repair_invoices(apps, schema_editor):
    """
    Copy every repairs.RepairInvoice into the shared invoice ledger. They
    keep their original RPR-INV-... codes (customers already hold those
    numbers); new repair invoices are numbered INV-#### like everything
    else. Repair bills were always created already paid at delivery.
    """
    RepairInvoice = apps.get_model("repairs", "RepairInvoice")
    Invoice = apps.get_model("sales", "Invoice")
    InvoiceItem = apps.get_model("sales", "InvoiceItem")
    for ri in RepairInvoice.objects.select_related("ticket").order_by("id"):
        invoice = Invoice.objects.create(
            code=ri.code, source="repair", party_id=ri.ticket.party_id, stock_point_id=ri.stock_point_id,
            repair_ticket_id=ri.ticket_id, repair_reopen_id=ri.reopen_id, date=ri.date,
            status=ri.status, pay_method="Collected at delivery" if ri.status == "Paid" else "",
            paid_on=ri.date if ri.status == "Paid" else None,
        )
        InvoiceItem.objects.create(
            invoice=invoice, description=f"Repair {ri.ticket.code}" + (" (follow-up visit)" if ri.reopen_id else ""),
            qty=1, price=ri.amount,
        )


def move_back(apps, schema_editor):
    RepairInvoice = apps.get_model("repairs", "RepairInvoice")
    Invoice = apps.get_model("sales", "Invoice")
    for inv in Invoice.objects.filter(source="repair").order_by("id"):
        RepairInvoice.objects.create(
            ticket_id=inv.repair_ticket_id, reopen_id=inv.repair_reopen_id, code=inv.code,
            amount=sum(i.qty * i.price for i in inv.items.all()), stock_point_id=inv.stock_point_id,
            status=inv.status, date=inv.date,
        )
        inv.items.all().delete()
        inv.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0005_invoice_sources"),
        ("repairs", "0006_alter_repairticketevent_event_type"),
    ]

    operations = [migrations.RunPython(move_repair_invoices, move_back)]
