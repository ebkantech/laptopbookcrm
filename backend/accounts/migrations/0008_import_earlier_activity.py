"""
Copy the staff actions that were ALREADY recorded before Activity Logs
existed into accounts.ActivityLog, marked source="imported":

  - repairs.RepairTicketEvent rows with a staff actor
  - rentals.RentalEvent rows with a staff actor
  - accounts.PermissionDeniedLog rows (outcome "denied")

Only what those tables actually hold is copied (who, what, when, which
ticket / agreement and, for repairs, its shop); event metadata is not
copied. Nothing else is reconstructed, and the source rows are left as
they are. `actor_privileged` uses the actor's superuser status now -- the
best that's known for older rows. Reversing removes only imported rows.
"""
from django.db import migrations

BATCH = 1000

PATH_MODULES = [
    ("/api/invoices", "sales"), ("/api/rental", "rentals"), ("/api/tickets", "repairs"), ("/api/repair", "repairs"),
    ("/api/products", "inventory"), ("/api/inventory", "inventory"), ("/api/parts", "inventory"),
    ("/api/stock-points", "stores"), ("/api/parties", "parties"), ("/api/messages", "parties"),
    ("/api/portal", "parties"), ("/api/cash", "accounting"), ("/api/bank", "accounting"),
    ("/api/warrant", "warranty"), ("/api/campaigns", "broadcast"), ("/api/whatsapp-orders", "broadcast"),
    ("/api/users", "staff"), ("/api/roles", "staff"), ("/api/notification", "staff"),
]


def _module(path):
    for prefix, module in PATH_MODULES:
        if path.startswith(prefix):
            return module
    return "security"


def _flush(ActivityLog, rows):
    if rows:
        ActivityLog.objects.bulk_create(rows, batch_size=BATCH)
        rows.clear()


def import_earlier(apps, schema_editor):
    ActivityLog = apps.get_model("accounts", "ActivityLog")
    RepairTicketEvent = apps.get_model("repairs", "RepairTicketEvent")
    RentalEvent = apps.get_model("rentals", "RentalEvent")
    PermissionDeniedLog = apps.get_model("accounts", "PermissionDeniedLog")
    rows = []

    for e in RepairTicketEvent.objects.filter(actor__isnull=False).select_related("ticket", "actor").iterator(chunk_size=BATCH):
        code = e.ticket.code
        rows.append(ActivityLog(
            actor_id=e.actor_id, actor_privileged=e.actor.is_superuser, at=e.at, module="repairs",
            action=e.event_type[:40], description=f"{e.get_event_type_display()} - repair ticket {code}"[:300],
            record_type="repairs.repairticket", record_id=str(e.ticket_id), record_label=code[:120],
            stock_point_id=e.ticket.stock_point_id, source="imported",
        ))
        if len(rows) >= BATCH:
            _flush(ActivityLog, rows)

    for e in RentalEvent.objects.filter(actor__isnull=False).select_related("rental", "actor").iterator(chunk_size=BATCH):
        code = e.rental.agreement_code or f"#{e.rental_id}"
        rows.append(ActivityLog(
            actor_id=e.actor_id, actor_privileged=e.actor.is_superuser, at=e.at, module="rentals",
            action=e.event_type[:40], description=f"{e.get_event_type_display()} - rental agreement {code}"[:300],
            record_type="rentals.rental", record_id=str(e.rental_id), record_label=code[:120], source="imported",
        ))
        if len(rows) >= BATCH:
            _flush(ActivityLog, rows)

    for d in PermissionDeniedLog.objects.select_related("user").iterator(chunk_size=BATCH):
        rows.append(ActivityLog(
            actor_id=d.user_id, actor_privileged=d.user.is_superuser, at=d.at, module=_module(d.path),
            action="denied", outcome="denied",
            description=f"Blocked: {d.method} {d.path[:120]} needs the “{d.required_perm}” permission"[:300],
            endpoint=f"{d.method} {d.path}"[:200], source="imported",
        ))
        if len(rows) >= BATCH:
            _flush(ActivityLog, rows)
    _flush(ActivityLog, rows)


def remove_imported(apps, schema_editor):
    apps.get_model("accounts", "ActivityLog").objects.filter(source="imported").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_activitylog"),
        ("repairs", "0008_undeliver_unpaid_repairs"),
        ("rentals", "0012_changes_requested_status"),
    ]

    operations = [migrations.RunPython(import_earlier, remove_imported)]
