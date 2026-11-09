"""
Inventory parts on a repair ticket: which parts can be picked, and taking the
chosen serial-numbered units out of stock when the ticket is created.

Eligible = serial-tracked products that are not laptops (Inventory's "Parts &
Accessories") with at least one unit IN_STOCK at the ticket's shop. Taking a
unit reuses the rental pattern (catalog.serials): lock the serial row, take one
off Stock.quantity with a guarded UPDATE, change the serial's status and write
its SerialEvent -- all inside the caller's transaction.
"""
from django.db import transaction
from django.db.models import F, Q
from rest_framework.exceptions import ValidationError

from catalog import serials as serial_tracking
from catalog.models import Product, Service, Stock, StockSerial

from .models import RepairPartUse

MAX_RESULTS = 20


def eligible_variants(stock_point_id, q=""):
    """[{variant, available}] for the product search: how many units are in stock at that shop.
    Serial numbers are never listed here -- staff type the one on the unit and it is checked."""
    serials = (StockSerial.objects.filter(stock_point_id=stock_point_id, status=StockSerial.IN_STOCK,
                                          variant__product__serial_tracking=True)
               .exclude(variant__product__category=Product.LAPTOP)
               .select_related("variant__product"))
    q = (q or "").strip()
    if q:
        serials = serials.filter(
            Q(variant__product__brand__icontains=q) | Q(variant__product__model_name__icontains=q)
            | Q(variant__product__product_code__icontains=q) | Q(variant__code__icontains=q)
            | Q(variant__spec__icontains=q) | Q(variant__product__description__icontains=q))
    out = {}
    for s in serials.order_by("variant__product__brand", "variant__product__model_name", "variant_id"):
        if s.variant_id not in out and len(out) >= MAX_RESULTS:
            continue
        out.setdefault(s.variant_id, {"variant": s.variant, "available": 0})["available"] += 1
    return list(out.values())


def matching_services(stock_point_id, q=""):
    """Catalogue repair services for the Work / Part search, each with the inventory part it
    fits (if any) and how many units of that part are in stock at the shop."""
    services = Service.objects.select_related("variant__product").order_by("label")
    q = (q or "").strip()
    if q:
        services = services.filter(label__icontains=q)
    out = []
    for service in services[:MAX_RESULTS]:
        available = 0
        if service.variant_id:
            available = StockSerial.objects.filter(variant_id=service.variant_id, stock_point_id=stock_point_id,
                                                   status=StockSerial.IN_STOCK).count()
        out.append({"service": service, "available": available})
    return out


def require_service_parts(lines, parts):
    """A booked service that fits an inventory part must come with that part's serial:
    one unit per line (quantity 1), and as many serials of that part as such lines."""
    needed = {}
    for n, line in enumerate(lines or [], 1):
        service = line.get("service")
        if service is not None and service.variant_id:
            if line.get("quantity", 1) != 1:
                raise ValidationError({"estimate_lines": f"Line {n}: {service.label} fits one {variant_label(service.variant)} -- book it once per unit (quantity 1)."})
            needed[service.variant_id] = needed.get(service.variant_id, 0) + 1
    given = {}
    for part in parts or []:
        given[part["variant"].id] = given.get(part["variant"].id, 0) + 1
    for variant_id, count in needed.items():
        if given.get(variant_id, 0) < count:
            service = next(l["service"] for l in lines if l.get("service") is not None and l["service"].variant_id == variant_id)
            raise ValidationError({"parts": [f"{service.label} fits {variant_label(service.variant)}: enter the serial number of the unit used."]})


def variant_label(variant):
    colour = f", {variant.colour}" if variant.colour else ""
    return f"{variant.product.display_name} · {variant.spec}{colour}"[:160]


def serial_problem(serial, variant, typed, stock_point):
    """Why `typed` can't be fitted from `stock_point`'s stock as `variant`, or None.
    Another shop's serial gets the same answer as an unknown one."""
    if serial is None or serial.stock_point_id != stock_point.id:
        return f"Serial {typed} was not found in stock at {stock_point.name}."
    if serial.variant_id != variant.id:
        return f"Serial {typed} does not belong to {variant_label(variant)}."
    if serial.variant.product.category == Product.LAPTOP:
        return "Laptops can't be used as repair parts."
    if not serial.variant.product.serial_tracking:
        return f"{variant_label(variant)} is not serial-tracked."
    if serial.status != StockSerial.IN_STOCK:
        return f"Serial {typed} is {serial.get_status_display().lower()}, not available."
    return None


def issue_parts(ticket, parts, actor):
    """Take every {variant, serial_number} in `parts` out of stock for `ticket`.
    All or nothing: any problem raises a ValidationError and the caller's
    transaction undoes the rest. Returns the RepairPartUse rows."""
    if not parts:
        return []
    errors, used = [], []
    seen = set()
    with transaction.atomic():
        for n, part in enumerate(parts, 1):
            variant, typed = part["variant"], part["serial_number"].strip()
            key = typed.upper()
            if key in seen:
                errors.append(f"Part {n}: serial {typed} is picked twice.")
                continue
            seen.add(key)
            serial = (StockSerial.objects.select_for_update(of=("self",)).select_related("variant__product")
                      .filter(serial_number__iexact=typed).first())
            problem = serial_problem(serial, variant, typed, ticket.stock_point)
            if problem:
                errors.append(f"Part {n}: {problem}")
            elif not Stock.objects.filter(variant_id=variant.id, stock_point_id=ticket.stock_point_id,
                                          quantity__gt=0).update(quantity=F("quantity") - 1):
                errors.append(f"Part {n}: no {variant_label(variant)} left on the shelf at {ticket.stock_point.name}.")
            else:
                serial_tracking.on_used_in_repair(serial, ticket.code, actor)
                used.append(RepairPartUse.objects.create(
                    ticket=ticket, variant=variant, serial=serial, stock_point=ticket.stock_point,
                    description=variant_label(variant), used_by=actor))
        if errors:
            raise ValidationError({"parts": errors})
    return used
