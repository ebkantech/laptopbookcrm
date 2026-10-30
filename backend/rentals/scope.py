from .models import RentalAsset


def rental_queryset_for(scope, qs):
    """
    Rental agreements have no store column of their own; the store link is
    each device's RentalAsset.source_stock_point (the shop it was taken
    from). Store staff see an agreement only when it has devices and every
    one of them came from their store -- an agreement mixing stores, or
    holding a device with no recorded store, stays Owner-only.
    `scope` is an accounts.store_scope.StoreScope.
    """
    if scope.all:
        return qs
    if scope.store_id is None:
        return qs.none()
    elsewhere = RentalAsset.objects.exclude(source_stock_point_id=scope.store_id)
    return qs.filter(lines__asset__source_stock_point_id=scope.store_id).exclude(lines__asset__in=elsewhere).distinct()
