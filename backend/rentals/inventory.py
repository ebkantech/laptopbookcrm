"""
Taking one laptop off a shop's sale stock into the rental fleet.

This is the only place sale stock is deducted for rentals. It is used by
create-agreement (the unit leaves stock only when its agreement is saved)
and by the older /rental-assets/from-inventory/ endpoint.

check_pick() runs every check that needs no lock; take() must be called
inside the caller's transaction.atomic(): it locks the stock row, takes
exactly one unit and creates (or revives) the RentalAsset, so a failure
anywhere later in that transaction puts the unit back automatically.
"""
from django.db import IntegrityError
from django.db.models import F
from rest_framework.exceptions import ValidationError

from catalog import serials as serial_tracking
from catalog.models import Stock
from catalog.status import require_active

from .models import RentalAsset
from .serializers import RentalAssetSerializer


def check_pick(stock, serial_number, asset_tag, scope):
    """
    Validate one inventory pick before anything is written. Returns the
    plan for take(): a retired asset to bring back (the same unit was put
    back on sale earlier) or a validated RentalAssetSerializer.
    """
    scope.require(stock.stock_point_id, "stock")
    require_active(stock.stock_point, "rentals", field="stock")
    variant, product = stock.variant, stock.variant.product
    typed = (serial_number or "").strip()
    if serial_tracking.tracked(variant) and serial_tracking.untracked_units(variant, stock.stock_point) == 0 \
            and not serial_tracking.in_stock_qs(variant, stock.stock_point).filter(serial_number__iexact=typed).exists():
        sample = ", ".join(serial_tracking.in_stock_qs(variant, stock.stock_point).values_list("serial_number", flat=True)[:5])
        raise ValidationError({"serial_number": f"Every unit of this product has a serial number -- enter the one on the unit you are renting out (in stock: {sample})."})
    if stock.quantity < 1:
        raise ValidationError({"stock": _none_left(stock)})
    returned = RentalAsset.objects.filter(
        serial_number__iexact=typed, status=RentalAsset.RETIRED, returned_to_stock_at__isnull=False,
    ).first()
    if returned:
        return returned
    asset_data = RentalAssetSerializer(data={
        "asset_tag": asset_tag or "",
        "serial_number": typed,
        "brand": product.brand if product.brand and product.brand != "—" else product.model_name.split()[0],
        "model_name": f"{product.model_name} ({variant.spec})"[:80],
    })
    asset_data.is_valid(raise_exception=True)
    return asset_data


def take(stock, plan, serial_number, actor):
    """
    Inside the caller's transaction: lock the stock row, take exactly one
    unit (never below zero) and create or revive the rental asset.
    """
    locked = Stock.objects.select_for_update().get(pk=stock.pk)
    if locked.quantity < 1:
        raise ValidationError({"stock": _none_left(stock)})
    Stock.objects.filter(pk=locked.pk).update(quantity=F("quantity") - 1)
    variant, shop, typed = stock.variant, stock.stock_point, (serial_number or "").strip()
    if isinstance(plan, RentalAsset):
        returned = RentalAsset.objects.select_for_update().get(pk=plan.pk)
        if returned.status != RentalAsset.RETIRED:
            raise ValidationError({"serial_number": f"Serial number {typed} was just added to the rental fleet by someone else."})
        returned.status = RentalAsset.AVAILABLE
        returned.variant, returned.source_stock_point = variant, shop
        returned.returned_to_stock_at = returned.returned_to = returned.returned_by = None
        returned.save()
        asset = returned
    else:
        try:
            asset = plan.save(variant=variant, source_stock_point=shop)
        except IntegrityError:
            # another request registered the same serial or tag after check_pick()
            raise ValidationError({"serial_number": f"Serial number {typed} or its asset tag was just registered by someone else."})
    serial_tracking.on_rented(variant, shop, typed, actor)
    return asset


def _none_left(stock):
    return f"No {stock.variant.product.display_name} ({stock.variant.spec}) left in stock at {stock.stock_point.name}."
