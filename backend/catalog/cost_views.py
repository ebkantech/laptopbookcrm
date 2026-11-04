"""
Cost review: the products whose cost is still the automatic guess (or
missing) and the spare parts with no cost, so they can be corrected one by
one or from a pasted / uploaded sheet. Costs are business-wide, so a store
Admin may correct only products and parts held at no other store; the Owner
/ Super Admin corrects any. Corrections apply to future sales; past invoice
lines keep the cost they were sold at (catalog.costing).
"""
from datetime import timedelta

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import activity
from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope
from .costing import set_cost
from .models import Part, PartStock, Stock, Variant

MAX_COST = 100_000_000
MAX_BULK = 2000


def _cost(value):
    try:
        cost = int(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        raise ValidationError({"cost": "Enter the cost as a whole number of rupees."})
    if not 1 <= cost <= MAX_COST:
        raise ValidationError({"cost": "Enter a cost between ₹1 and ₹10,00,00,000."})
    return cost


def _may_edit(user, stock_model, **key):
    scope = StoreScope(user)
    if scope.owner:
        return True
    if scope.store_id is None:
        return False
    return not stock_model.objects.filter(quantity__gt=0, **key).exclude(stock_point_id=scope.store_id).exists()


def _check(user, stock_model, what, **key):
    if not _may_edit(user, stock_model, **key):
        raise PermissionDenied(f"{what} is also stocked at another store, so only the Owner can change its cost.")


def _variant_row(v, sold):
    return {"id": v.id, "code": v.code, "product": v.product.display_name, "spec": v.spec, "colour": v.colour,
            "sell_price": v.sell_price, "cost": v.cost, "cost_estimated": v.cost_estimated,
            "in_stock": v.in_stock or 0, "sold_90d": sold.get(v.id, 0)}


class CostReviewView(APIView):
    """GET: variants with a guessed or zero cost (most sold first) and parts with no cost.
    The list is the shared catalogue; units in stock and units sold are counted
    at the stores in view only, so a store account sees nothing of another store."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def get(self, request):
        from sales.models import InvoiceItem

        scope = StoreScope(request.user)
        stores = None if scope.all else ([scope.store_id] if scope.store_id is not None else [])
        here = (lambda path: Q()) if stores is None else (lambda path: Q(**{f"{path}__in": stores}))
        since = timezone.localdate() - timedelta(days=90)
        sold = dict(InvoiceItem.objects.filter(here("invoice__stock_point_id"), invoice__date__gte=since,
                                               invoice__status__in=("Paid", "Refunded"), variant__isnull=False)
                    .values_list("variant_id").order_by().annotate(n=Sum("qty")).values_list("variant_id", "n"))
        variants = (Variant.objects.select_related("product").filter(Q(cost_estimated=True) | Q(cost=0))
                    .annotate(in_stock=Sum("stock__quantity", filter=here("stock__stock_point_id"))))
        rows = sorted((_variant_row(v, sold) for v in variants), key=lambda r: (-r["sold_90d"], -r["in_stock"], r["product"]))
        parts = Part.objects.filter(cost=0).annotate(in_stock=Sum("stock__quantity", filter=here("stock__stock_point_id"))).order_by("name")
        total = Variant.objects.count()
        return Response({
            "variants": rows,
            "parts": [{"id": p.id, "code": p.slug, "name": p.name, "cost": p.cost, "in_stock": p.in_stock or 0} for p in parts],
            "summary": {"variants_total": total, "variants_to_fix": len(rows), "parts_to_fix": parts.count()},
        })


class VariantCostView(APIView):
    """POST {cost}: the real purchase cost of one product variant."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def post(self, request, pk):
        variant = get_object_or_404(Variant.objects.select_related("product"), pk=pk)
        _check(request.user, Stock, f"{variant.product.display_name} ({variant.spec})", variant=variant)
        cost = _cost(request.data.get("cost"))
        old = set_cost(variant, cost)
        activity.note(variant, "cost", f"Cost of {variant.code} set to ₹{cost:,} (was ₹{old:,})", changes={"cost": (old, cost)})
        return Response({"id": variant.id, "code": variant.code, "cost": variant.cost, "cost_estimated": False})


class PartCostView(APIView):
    """POST {cost}: the purchase cost of one spare part."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def post(self, request, pk):
        part = get_object_or_404(Part, pk=pk)
        _check(request.user, PartStock, part.name, part=part)
        cost = _cost(request.data.get("cost"))
        old, part.cost = part.cost, cost
        part.save(update_fields=["cost"])
        activity.note(part, "cost", f"Cost of part {part.name} set to ₹{cost:,} (was ₹{old:,})", changes={"cost": (old, cost)})
        return Response({"id": part.id, "code": part.slug, "cost": part.cost})


class BulkCostView(APIView):
    """
    POST {rows: [{code, cost}]} -- code is a variant SKU (VC-SKU-0013) or a
    part code (its slug). Every row is checked first; nothing is saved unless
    all rows are valid, and the reply lists exactly what was wrong.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def post(self, request):
        rows = request.data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValidationError({"rows": "Send at least one row of code and cost."})
        if len(rows) > MAX_BULK:
            raise ValidationError({"rows": f"At most {MAX_BULK} rows at a time."})
        variants = {v.code.upper(): v for v in Variant.objects.select_related("product")}
        parts = {p.slug.upper(): p for p in Part.objects.all()}
        plan, problems = [], []
        for n, row in enumerate(rows, start=1):
            code = str((row or {}).get("code", "")).strip().upper()
            try:
                cost = _cost((row or {}).get("cost"))
            except ValidationError:
                problems.append(f"Row {n} ({code or 'no code'}): the cost isn't a whole number between 1 and 10,00,00,000.")
                continue
            target = variants.get(code) or parts.get(code)
            if target is None:
                problems.append(f"Row {n}: no product variant or part has the code {code or '(blank)'}.")
                continue
            is_variant = isinstance(target, Variant)
            name = f"{target.product.display_name} ({target.spec})" if is_variant else target.name
            if not (_may_edit(request.user, Stock, variant=target) if is_variant else _may_edit(request.user, PartStock, part=target)):
                problems.append(f"Row {n} ({code}): {name} is also stocked at another store -- only the Owner can change its cost.")
                continue
            plan.append((target, cost, is_variant, code))
        if problems:
            return Response({"saved": 0, "problems": problems}, status=400)
        for target, cost, is_variant, code in plan:
            if is_variant:
                old = set_cost(target, cost)
            else:
                old, target.cost = target.cost, cost
                target.save(update_fields=["cost"])
            activity.note(target, "cost", f"Cost of {code} set to ₹{cost:,} (was ₹{old:,}) -- bulk update", changes={"cost": (old, cost)})
        return Response({"saved": len(plan), "problems": []})
