"""
Purchase costs, for real profit (reports.profit_loss).

  - Variant.cost is the weighted average of what was actually paid: units
    received at a new purchase price are averaged with the units already in
    stock (all stores). A guessed cost is replaced outright by the first real one.
  - Variant.cost_estimated marks the automatic guess (78% of the selling
    price) used when no purchase price was entered.
  - Each invoice line locks the cost at sale (sales.InvoiceItem.unit_cost),
    so correcting a cost later never rewrites past months.
"""
from django.db.models import Sum

ESTIMATED_COST_SHARE = 0.78


def estimate(sell_price):
    return round(sell_price * ESTIMATED_COST_SHARE)


def units_in_stock(variant):
    from .models import Stock

    return Stock.objects.filter(variant=variant).aggregate(n=Sum("quantity"))["n"] or 0


def average_in(variant, units_before, qty, unit_cost):
    """The variant's cost after `qty` units bought at `unit_cost` join
    `units_before` units already held. Returns the changed fields."""
    if variant.cost_estimated or units_before <= 0 or not variant.cost:
        new = unit_cost
    else:
        new = round((units_before * variant.cost + qty * unit_cost) / (units_before + qty))
    old = (variant.cost, variant.cost_estimated)
    variant.cost, variant.cost_estimated = new, False
    variant.save(update_fields=["cost", "cost_estimated"])
    return {"cost": (old[0], new)} if old[0] != new or old[1] else {}


def set_cost(variant, cost):
    """A cost typed in by hand (the cost review list): taken as the real cost."""
    old = variant.cost
    variant.cost, variant.cost_estimated = int(cost), False
    variant.save(update_fields=["cost", "cost_estimated"])
    return old
