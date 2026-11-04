"""
Serial-number tracing. Units of a product with serial_tracking carry the
app's own serial (catalog.new_product.generate_serials). This module moves
each unit through its life and keeps its history (SerialEvent):

  received -> in stock -> sold (picked on the sale invoice)
                       -> on rent (taken from inventory for a rental)
                       -> written off (lost / damaged / sold before tracking)
  sold     -> back in stock (invoice cancelled, or returned and restocked)
           -> returned, not restocked (returned damaged)

Units received before serials existed have none. A sale or return may skip
a serial only for those units: the number of untracked units is the shelf
quantity minus the serials in stock.
"""
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import SerialEvent, Stock, StockSerial


def log(serial, event, text, actor=None, stock_point_id=None, invoice=None):
    return SerialEvent.objects.create(serial=serial, event=event, text=text[:300], actor=actor,
                                      stock_point_id=stock_point_id or serial.stock_point_id, invoice=invoice)


def tracked(variant):
    return bool(variant.product.serial_tracking)


def in_stock_qs(variant, stock_point):
    sp_id = getattr(stock_point, "pk", stock_point)
    return StockSerial.objects.filter(variant=variant, stock_point_id=sp_id, status=StockSerial.IN_STOCK)


def untracked_units(variant, stock_point, shelf_qty=None):
    """Units on this shelf that never had a serial number."""
    sp_id = getattr(stock_point, "pk", stock_point)
    if shelf_qty is None:
        row = Stock.objects.filter(variant=variant, stock_point_id=sp_id).first()
        shelf_qty = row.quantity if row else 0
    return max(0, shelf_qty - in_stock_qs(variant, sp_id).count())


def _clean(values):
    out, seen = [], set()
    for v in values or []:
        v = str(v or "").strip().upper()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ------------------------------------------------------------------- sale

def check_sale_lines(items, stock_point, shelf):
    """Before stock is taken: every tracked line names enough of its own in-stock
    units. `shelf` maps variant id -> quantity on the shelf now. Returns the
    StockSerial rows per line (same order as items)."""
    problems, picked, used, budget = [], [], set(), {}
    for item in items:
        variant, qty = item["variant"], item["qty"]
        wanted = _clean(item.get("serials"))
        if not tracked(variant):
            if wanted:
                problems.append(f"{variant.product.display_name} doesn't use serial numbers.")
            picked.append([])
            continue
        name = f"{variant.product.display_name} ({variant.spec})"
        if len(wanted) > qty:
            problems.append(f"{name}: {len(wanted)} serial numbers for {qty} unit{'s' if qty != 1 else ''}.")
        rows = list(StockSerial.objects.select_for_update().select_related("stock_point").filter(serial_number__in=wanted)) if wanted else []
        found = {r.serial_number.upper(): r for r in rows}
        for sn in wanted:
            r = found.get(sn)
            if not r or r.variant_id != variant.id:
                problems.append(f"{sn} is not a unit of {name}.")
            elif r.stock_point_id != stock_point.id:
                problems.append(f"{sn} is at {r.stock_point.name}, not {stock_point.name}.")
            elif r.status != StockSerial.IN_STOCK:
                problems.append(f"{sn} is {r.get_status_display().lower()}, not in stock.")
            elif sn in used:
                problems.append(f"{sn} is on two lines.")
            used.add(sn)
        # units going out without a serial must come from the ones that never had one
        if variant.id not in budget:
            budget[variant.id] = untracked_units(variant, stock_point, shelf.get(variant.id, 0))
        without = max(0, qty - len(wanted))
        if without > budget[variant.id]:
            need = qty - budget[variant.id]
            problems.append(f"{name}: pick the serial number of {'each unit' if need >= qty else f'{need} of the {qty} units'} sold "
                            f"({len(wanted)} chosen).")
        budget[variant.id] = max(0, budget[variant.id] - without)
        picked.append([found[sn] for sn in wanted if sn in found])
    if problems:
        raise ValidationError({"items": problems})
    return picked


def mark_sold(invoice, picked, actor):
    now = timezone.now()
    for item, rows in zip(invoice.items.order_by("id"), picked):
        for r in rows:
            r.status, r.invoice_item, r.sold_at = StockSerial.SOLD, item, now
            r.save(update_fields=["status", "invoice_item", "sold_at"])
            log(r, SerialEvent.SOLD, f"Sold on {invoice.code} to {invoice.party.name}", actor, invoice=invoice)


def on_sale_cancelled(invoice, actor):
    for r in StockSerial.objects.filter(invoice_item__invoice=invoice, status=StockSerial.SOLD):
        r.status, r.sold_at = StockSerial.IN_STOCK, None
        r.save(update_fields=["status", "sold_at"])
        log(r, SerialEvent.SALE_CANCELLED, f"Back in stock -- invoice {invoice.code} cancelled", actor, invoice=invoice)


# ----------------------------------------------------------------- return

def check_return(item, qty, serials, already_returned):
    """Which of this line's sold units are coming back. Required for every
    returned unit that left with a serial (units sold without one may be skipped)."""
    wanted = _clean(serials)
    sold = {r.serial_number.upper(): r for r in item.serials.filter(status=StockSerial.SOLD)}
    for sn in wanted:
        if sn not in sold:
            raise ValidationError({"detail": f"{sn} wasn't sold on this line (or is already back)."})
    if len(wanted) > qty:
        raise ValidationError({"detail": f"{item.label}: {len(wanted)} serial numbers for {qty} returned."})
    untracked_left = max(0, (item.qty - already_returned) - len(sold))
    need = max(0, qty - untracked_left)
    if len(wanted) < need:
        raise ValidationError({"detail": f"{item.label}: pick the serial number of each unit coming back ({len(wanted)} of {need})."})
    return [sold[sn] for sn in wanted]


def mark_returned(rows, invoice, restock, actor):
    for r in rows:
        if restock:
            r.status = StockSerial.IN_STOCK
            r.stock_point_id = invoice.stock_point_id
            text = f"Returned on {invoice.code} and put back in stock"
        else:
            r.status = StockSerial.RETURNED
            text = f"Returned on {invoice.code} -- not restocked (damaged)"
        r.save(update_fields=["status", "stock_point"])
        log(r, SerialEvent.RETURNED, text, actor, invoice=invoice)


# ------------------------------------------------------------------ rental

def on_rented(variant, stock_point, serial_number, actor):
    r = in_stock_qs(variant, stock_point).filter(serial_number__iexact=(serial_number or "").strip()).first()
    if r:
        r.status = StockSerial.RENTED
        r.save(update_fields=["status"])
        log(r, SerialEvent.RENTED, "Taken from stock for rent", actor)
    return r


def on_back_from_rent(serial_number, stock_point, actor):
    r = StockSerial.objects.filter(serial_number__iexact=(serial_number or "").strip(), status=StockSerial.RENTED).first()
    if r:
        r.status, r.stock_point = StockSerial.IN_STOCK, stock_point
        r.save(update_fields=["status", "stock_point"])
        log(r, SerialEvent.BACK_FROM_RENT, f"Back from rent into stock at {stock_point.name}", actor)
    return r


# --------------------------------------------------------------- write-off

def write_off(serial, actor, reason, reduce_stock):
    """Close a unit that is no longer on the shelf. reduce_stock=True also takes
    one off the quantity (lost / damaged now); False when the quantity already
    went down earlier (a unit sold or used before serials were tracked)."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why (lost, damaged, sold before tracking...)."})
    serial = StockSerial.objects.select_for_update().get(pk=serial.pk)
    if serial.status != StockSerial.IN_STOCK:
        raise ValidationError({"detail": f"{serial.serial_number} is {serial.get_status_display().lower()}, not in stock."})
    if reduce_stock and not Stock.objects.filter(variant_id=serial.variant_id, stock_point_id=serial.stock_point_id,
                                                 quantity__gt=0).update(quantity=F("quantity") - 1):
        raise ValidationError({"detail": "The shelf quantity is already 0 -- write it off without reducing stock."})
    serial.status = StockSerial.WRITTEN_OFF
    serial.save(update_fields=["status"])
    log(serial, SerialEvent.WRITTEN_OFF, f"Written off{' (stock reduced by 1)' if reduce_stock else ''} -- {reason[:200]}", actor)
    return serial


# ------------------------------------------------------------------ trace

def trace(serial):
    from repairs.models import RepairTicket
    from warranty.models import Warranty

    item = serial.invoice_item
    invoice = item.invoice if item else None
    product = serial.variant.product
    warranties = Warranty.objects.filter(invoice=invoice) if invoice else Warranty.objects.none()
    repairs = RepairTicket.objects.filter(serial__iexact=serial.serial_number).order_by("-id")
    return {
        "serial_number": serial.serial_number, "status": serial.status, "status_label": serial.get_status_display(),
        "product": product.display_name, "product_id": product.id, "product_code": product.product_code,
        "spec": serial.variant.spec, "colour": serial.variant.colour, "variant_code": serial.variant.code,
        "stock_point": serial.stock_point.name, "received_at": serial.received_at,
        "sale": {"invoice": invoice.code, "invoice_id": invoice.id, "date": invoice.date, "customer": invoice.party.name,
                 "phone": invoice.party.phone, "price": item.price, "invoice_status": invoice.status} if invoice else None,
        "warranties": [{"id": w.id, "item": w.item_label, "end_date": w.end_date, "status": w.status,
                        "claims": w.claims.count()} for w in warranties],
        "repairs": [{"id": t.id, "code": t.code, "status": t.status, "received": t.received} for t in repairs[:20]],
        "events": [{"event": e.event, "text": e.text, "at": e.at, "store": e.stock_point.name if e.stock_point else "",
                    "by": (e.actor.get_full_name() or e.actor.username) if e.actor else "",
                    "invoice": e.invoice.code if e.invoice else None}
                   for e in serial.events.select_related("stock_point", "actor", "invoice")],
    }


def release_for_revision(invoice, actor):
    """An unpaid sale is being edited: its units go back in stock so the new
    lines can keep the same units or pick others (sales.serializers.update)."""
    for r in StockSerial.objects.filter(invoice_item__invoice=invoice, status=StockSerial.SOLD):
        r.status, r.sold_at, r.invoice_item = StockSerial.IN_STOCK, None, None
        r.save(update_fields=["status", "sold_at", "invoice_item"])
        log(r, SerialEvent.SALE_CANCELLED, f"Back in stock -- invoice {invoice.code} revised", actor, invoice=invoice)
