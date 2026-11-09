"""
The life of one rental laptop, for the Device button: where it came
from, every customer who rented it, the problems raised while it was out,
every repair job on its serial number, and when it went back on sale.

Repairs are matched by serial number, so a job booked before the unit
joined the rental fleet (or after it was sold) shows up too.
"""
from catalog.models import SerialEvent, StockSerial
from repairs.models import RepairTicket

from .models import Rental, RentalEvent, RentalIssue, RentalLine, add_months


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _end_date(rental):
    """The last day of the agreement's term (start + tenure)."""
    return add_months(rental.start, rental.tenure_months) if rental.start and rental.tenure_months else None


def device_history(asset):
    lines = (
        RentalLine.objects.filter(asset=asset)
        .select_related("rental__party", "handover_by")
        .prefetch_related("rental__lines")
        .order_by("-rental__start", "-id")
    )
    rentals = [line.rental for line in lines]
    events = {
        (e.rental_id, e.event_type): e
        for e in RentalEvent.objects.filter(
            rental__in=rentals, event_type__in=(RentalEvent.DEVICE_CHECKED_OUT, RentalEvent.AGREEMENT_CLOSED,
                                                RentalEvent.AGREEMENT_CANCELLED))
        .select_related("actor").order_by("at")
    }
    issues_by_rental = {}
    for issue in RentalIssue.objects.filter(rental__in=rentals).select_related("assigned_to").order_by("-raised_at"):
        issues_by_rental.setdefault(issue.rental_id, []).append(issue)

    timeline = []
    agreements = []
    for line in lines:
        rental = line.rental
        handed = events.get((rental.id, RentalEvent.DEVICE_CHECKED_OUT))
        closed = events.get((rental.id, RentalEvent.AGREEMENT_CLOSED)) or events.get((rental.id, RentalEvent.AGREEMENT_CANCELLED))
        devices = len(rental.lines.all())
        issues = issues_by_rental.get(rental.id, [])
        agreements.append({
            "rental_id": rental.id, "agreement_code": rental.agreement_code or f"#{rental.id}",
            "status": rental.status, "status_label": rental.get_status_display(),
            "party_id": rental.party_id, "customer": rental.party.name, "phone": rental.party.phone,
            "customer_type": rental.party.get_type_display() if rental.party.type else "",
            "start": rental.start, "end": _end_date(rental), "tenure_months": rental.tenure_months,
            "monthly_fee": line.monthly_fee, "devices_on_agreement": devices,
            "handed_over_at": handed.at if handed else None, "handed_over_by": _name(handed.actor) if handed else "",
            "closed_at": closed.at if closed else None,
            "condition_notes": line.condition_notes,
            "accessories": [a.get("name") for a in (line.accessories or []) if a.get("name")],
            "handover_by": _name(line.handover_by),
            "issues": [{
                "id": i.id, "title": i.title, "description": i.description, "status": i.status,
                "assigned_to": _name(i.assigned_to), "raised_at": i.raised_at, "resolved_at": i.resolved_at,
            } for i in issues],
        })
        who = f"{rental.party.name} ({rental.agreement_code or rental.id})"
        if handed:
            timeline.append({"at": handed.at, "kind": "rented", "text": f"Handed to {who}", "by": _name(handed.actor)})
        if closed:
            verb = "returned -- agreement closed" if closed.event_type == RentalEvent.AGREEMENT_CLOSED else "agreement cancelled"
            timeline.append({"at": closed.at, "kind": "back", "text": f"Back from {who}: {verb}", "by": _name(closed.actor)})
        for i in issues:
            timeline.append({"at": i.raised_at, "kind": "issue", "text": f"Problem raised: {i.title}",
                             "by": f"assigned to {_name(i.assigned_to)}" if i.assigned_to else "not assigned"})
            if i.resolved_at:
                timeline.append({"at": i.resolved_at, "kind": "issue_resolved", "text": f"Problem resolved: {i.title}",
                                 "by": _name(i.assigned_to)})

    repairs = []
    serial = (asset.serial_number or "").strip()
    tickets = RepairTicket.objects.filter(serial__iexact=serial).select_related(
        "party", "assigned_to", "worked_by", "diagnosed_by", "stock_point").order_by("-received", "-id") if serial else []
    for t in tickets:
        repairs.append({
            "id": t.id, "code": t.code, "status": t.status, "received": t.received, "store": t.stock_point.name,
            "customer": t.party.name, "problem": t.issue,
            "assigned_to": _name(t.assigned_to), "worked_by": _name(t.worked_by),
            "diagnosis": t.diagnosis_note, "diagnosed_by": _name(t.diagnosed_by),
            "ready_at": t.ready_at,
        })
        timeline.append({"at": t.received, "kind": "repair", "text": f"Repair {t.code} booked: {t.issue[:120]}",
                         "by": f"repair staff: {_name(t.assigned_to)}" if t.assigned_to else "not assigned yet"})

    # Stock-side steps for a serial-tracked unit: received, rented out, back on sale...
    unit = StockSerial.objects.filter(serial_number__iexact=serial).select_related("stock_point").first() if serial else None
    if unit:
        for e in unit.events.select_related("stock_point", "actor").exclude(event__in=(SerialEvent.RENTED,)):
            timeline.append({"at": e.at, "kind": "stock", "text": e.text or e.event.replace("_", " ").capitalize(),
                             "by": _name(e.actor), "store": e.stock_point.name if e.stock_point else ""})
    timeline.append({"at": asset.created_at, "kind": "joined",
                     "text": f"Added to the rental fleet{f' from {asset.source_stock_point.name} stock' if asset.variant_id and asset.source_stock_point else ''}",
                     "by": ""})
    if asset.returned_to_stock_at:
        timeline.append({"at": asset.returned_to_stock_at, "kind": "on_sale",
                         "text": f"Put back on sale at {asset.returned_to.name if asset.returned_to else 'a shop'}",
                         "by": _name(asset.returned_by)})

    def sort_key(row):
        at = row["at"]
        return at.isoformat() if hasattr(at, "isoformat") else str(at)

    timeline.sort(key=sort_key, reverse=True)
    current = next((a for a in agreements if a["status"] in (Rental.ACTIVE, Rental.APPROVED, Rental.PENDING_APPROVAL)), None)
    return {
        "device": {
            "id": asset.id, "asset_tag": asset.asset_tag, "serial_number": asset.serial_number,
            "brand": asset.brand, "model_name": asset.model_name,
            "status": asset.status, "status_label": asset.get_status_display(),
            "added_at": asset.created_at, "from_store": asset.source_stock_point.name if asset.source_stock_point else "",
            "from_inventory": bool(asset.variant_id),
            "product_code": asset.variant.product.product_code if asset.variant_id else "",
            "variant_code": asset.variant.code if asset.variant_id else "",
        },
        "summary": {
            "times_rented": sum(1 for a in agreements if a["handed_over_at"] or a["status"] in (Rental.ACTIVE, Rental.CLOSED)),
            "customers": len({a["party_id"] for a in agreements}),
            "problems": sum(len(a["issues"]) for a in agreements),
            "repairs": len(repairs),
            "current_customer": current["customer"] if current else "",
        },
        "agreements": agreements,
        "repairs": repairs,
        "timeline": timeline,
    }
