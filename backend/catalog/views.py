import logging

from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import activity
from accounts.models import User
from accounts.permissions import HasPerm, IsStaffAccount
from accounts.store_scope import StoreScope, StoreScopedMixin
from .models import Part, PartStock, Product, Service, Stock, StockPoint, StockSerial, Variant
from .status import can_manage_status, require_active
from .serializers import (
    PartSerializer, ProductSerializer, ServiceSerializer, StockPointSerializer, StockSerializer,
    StoreStockRowSerializer, VariantSerializer,
)
from .utils import next_code
from . import new_product


STORE_RECENT_LIMIT = 5
# The business's existing low-stock line (ProductViewSet.low_stock): four
# units or fewer. Store Locator applies it per stock point.
LOW_STOCK_THRESHOLD = 4
STORE_ADMIN_DETAIL = "Only the Owner or Super Admin can add or edit stores and channels."
STATUS_ADMIN_DETAIL = "Only a Superuser or an administrator can activate or deactivate stores and channels."

audit = logging.getLogger("accounts.audit")


# Store-scoped prefetches: a product / part is catalogue-wide, but the
# stock rows nested under it belong to stores, so a store-assigned account
# only ever gets its own store's rows (and totals computed from them).
def stock_prefetch(scope, path="stock"):
    return Prefetch(path, queryset=scope.filter(Stock.objects.select_related("stock_point"), "stock_point"))


def part_stock_prefetch(scope, path="stock"):
    return Prefetch(path, queryset=scope.filter(PartStock.objects.select_related("stock_point"), "stock_point"))


def product_queryset(user):
    scope = StoreScope(user)
    variants = Variant.objects.prefetch_related(stock_prefetch(scope))
    return Product.objects.prefetch_related(Prefetch("variants", queryset=variants))


class StockPointViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    Shops and online channels. Everyone reads within their store scope;
    only the Owner / Super Admin creates or edits one. An edit updates the
    same row in place (same id), so every record linked to it shows the
    new details on its next fetch. There is no delete: stock, invoices and
    repair tickets protect the row.
    """
    queryset = StockPoint.objects.all()
    serializer_class = StockPointSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    def get_queryset(self):
        # Owner: every shop and channel, whichever store is in view (this is
        # the store directory). Store staff: only the store they're working in.
        scope = StoreScope(self.request.user)
        qs = super().get_queryset() if scope.owner else scope.filter(super().get_queryset(), "id")
        # ?active=1 -- the choices for a NEW operation (invoice, repair,
        # stock, rental, staff assignment): inactive stock points are left
        # out. Without it every stock point is listed, for history and filters.
        if self.action == "list" and self.request.query_params.get("active") in ("1", "true"):
            qs = qs.filter(is_active=True)
        return qs

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        """
        Activate / deactivate a shop or channel. Body: {"is_active": bool}.
        Superuser, Owner and staff administrators only (catalog.status);
        anyone else gets 403 before the store is even looked up. Only the
        flag changes -- every linked record stays as it is.
        """
        if not can_manage_status(request.user):
            raise PermissionDenied(STATUS_ADMIN_DETAIL)
        value = request.data.get("is_active")
        if not isinstance(value, bool):
            return Response({"is_active": ["Send true to activate or false to deactivate."]}, status=400)
        sp = self.get_object()  # store-scoped: another store's id is a 404
        if sp.is_active != value:
            sp.is_active = value
            sp.save(update_fields=["is_active"])
            audit.info("store-admin action=%s actor=%s target=%s", "activate" if value else "deactivate",
                       request.user.pk, sp.pk)
        return Response(self.get_serializer(sp).data)

    def create(self, request, *args, **kwargs):
        StoreScope(request.user).require_owner(STORE_ADMIN_DETAIL)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        StoreScope(request.user).require_owner(STORE_ADMIN_DETAIL)
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        sp = serializer.save()
        audit.info("store-admin action=create actor=%s target=%s slug=%s", self.request.user.pk, sp.pk, sp.slug)

    def perform_update(self, serializer):
        before = {f: getattr(serializer.instance, f) for f in serializer.validated_data}
        sp = serializer.save()
        changed = ",".join(sorted(f for f, old in before.items() if getattr(sp, f) != old)) or "none"
        audit.info("store-admin action=update actor=%s target=%s fields=%s", self.request.user.pk, sp.pk, changed)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Store Locator cards: per stock point, how many product units and
        stock rows (catalog.Stock) and spare-part units and rows
        (catalog.PartStock) it holds. Two grouped queries, no per-store loop.
        """
        if not request.user.has_perm_code("storelocator.view"):
            raise PermissionDenied("Your role doesn't include the Store Locator.")
        scope = StoreScope(request.user)
        rows = {sp.id: {"id": sp.id, "product_units": 0, "stock_records": 0, "out_of_stock": 0, "low_stock": 0,
                        "part_units": 0, "part_records": 0}
                for sp in self.get_queryset()}
        stock = scope.filter(Stock.objects.all(), "stock_point")
        part_stock = scope.filter(PartStock.objects.all(), "stock_point")
        # out_of_stock / low_stock count existing stock records only: a record
        # at 0 is a verified zero; a variant with no record isn't counted.
        per_point = stock.order_by().values("stock_point_id").annotate(
            units=Sum("quantity"), records=Count("id"),
            out=Count("id", filter=Q(quantity=0)),
            low=Count("id", filter=Q(quantity__gt=0, quantity__lte=LOW_STOCK_THRESHOLD)),
        )
        for r in per_point:
            rows[r["stock_point_id"]].update(
                product_units=r["units"] or 0, stock_records=r["records"], out_of_stock=r["out"], low_stock=r["low"],
            )
        for r in part_stock.order_by().values("stock_point_id").annotate(units=Sum("quantity"), records=Count("id")):
            rows[r["stock_point_id"]].update(part_units=r["units"] or 0, part_records=r["records"])
        for row in rows.values():
            row["staff_count"] = 0
        staff = scope.filter(User.objects.filter(is_active=True, stock_point__isnull=False), "stock_point")
        for r in staff.order_by().values("stock_point_id").annotate(n=Count("id")):
            if r["stock_point_id"] in rows:
                rows[r["stock_point_id"]]["staff_count"] = r["n"]
        return Response(list(rows.values()))

    @action(detail=False, methods=["get"])
    def inventory(self, request):
        """
        Inventory across the stock points this account may see, for the
        Store Locator's by-channel / by-product / by-store views: every
        catalogue variant and repair part, each with its stock records at
        those stock points (quantity and bin). A missing record is simply
        absent from `stock` -- it is not reported as zero. No cost prices.
        """
        if not request.user.has_perm_code("storelocator.view"):
            raise PermissionDenied("Your role doesn't include the Store Locator.")
        scope = StoreScope(request.user)
        points = list(self.get_queryset())
        payload = {
            "low_stock_threshold": LOW_STOCK_THRESHOLD,
            "stock_points": StockPointSerializer(points, many=True, context={"request": request}).data,
            "variants": [], "parts": [],
        }
        if not scope.assigned:
            return Response(payload)
        stock = scope.filter(Stock.objects.only("id", "variant_id", "stock_point_id", "quantity", "location"), "stock_point")
        variants = (
            Variant.objects.select_related("product")
            .prefetch_related(Prefetch("stock", queryset=stock))
            .order_by("product__brand", "product__model_name", "code")
        )
        payload["variants"] = [
            {
                "variant_id": v.id, "variant_code": v.code, "spec": v.spec, "mrp": v.mrp, "sell_price": v.sell_price,
                "product_id": v.product_id, "product_name": v.product.display_name, "brand": v.product.brand,
                "model_name": v.product.model_name, "product_code": v.product.product_code,
                "processor": v.product.processor, "condition": v.product.condition,
                "stock": [{"id": s.id, "stock_point_id": s.stock_point_id, "quantity": s.quantity, "location": s.location}
                          for s in v.stock.all()],
            }
            for v in variants
        ]
        part_stock = scope.filter(PartStock.objects.all(), "stock_point")
        parts = Part.objects.prefetch_related(Prefetch("stock", queryset=part_stock)).order_by("name")
        payload["parts"] = [
            {
                "part_id": p.id, "slug": p.slug, "name": p.name, "compatible_brands": p.compatible_brands,
                "stock": [{"id": s.id, "stock_point_id": s.stock_point_id, "quantity": s.quantity} for s in p.stock.all()],
            }
            for p in parts
        ]
        return Response(payload)

    @action(detail=True, methods=["get"])
    def locator(self, request, pk=None):
        """
        Everything the Store Locator shows for one stock point, scoped to
        that stock point only: its product and spare-part stock, plus
        repair / invoice / rental-asset summaries. Each business section
        is only filled in when the user holds that module's existing view
        permission -- otherwise it comes back as {"restricted": true}.
        No customer names or contact details are returned.
        """
        from rentals.models import RentalAsset
        from repairs.models import RepairTicket
        from sales.models import Invoice

        sp = self.get_object()  # store-scoped: another store's id is a 404
        user = request.user
        stock = Stock.objects.filter(stock_point=sp).select_related("variant__product").order_by(
            "variant__product__brand", "variant__product__model_name", "variant__code",
        )
        parts = PartStock.objects.filter(stock_point=sp).select_related("part").order_by("part__name")

        repairs = {"restricted": True}
        if user.has_perm_code("repairs.view"):
            tickets = RepairTicket.objects.filter(stock_point=sp)
            by_status = {r["status"]: r["n"] for r in tickets.order_by().values("status").annotate(n=Count("id"))}
            repairs = {
                "restricted": False,
                "total": sum(by_status.values()),
                "open": sum(n for s, n in by_status.items() if s != RepairTicket.DELIVERED),
                "by_status": [{"status": s, "count": by_status.get(s, 0)} for s in RepairTicket.STAGES],
                "recent": [
                    {"id": t.id, "code": t.code, "device": f"{t.brand} {t.model_name}".strip(),
                     "status": t.status, "received": t.received}
                    for t in tickets.order_by("-received", "-id")[:STORE_RECENT_LIMIT]
                ],
            }

        invoices = {"restricted": True}
        if user.has_perm_code("invoices.view"):
            # Same money rules as reports.SalesSummaryReportView: cancelled
            # invoices are ignored, collected = net of refunds on settled ones,
            # pending = full total of the still-outstanding ones.
            live = list(
                Invoice.objects.filter(stock_point=sp).exclude(status=Invoice.CANCELLED)
                .prefetch_related("items", "refunds")
            )
            settled = [i for i in live if i.status in Invoice.SETTLED]
            outstanding = [i for i in live if i.status in Invoice.OUTSTANDING]
            invoices = {
                "restricted": False,
                "count": len(live),
                "cancelled": Invoice.objects.filter(stock_point=sp, status=Invoice.CANCELLED).count(),
                "by_source": [
                    {"source": key, "label": label, "count": sum(1 for i in live if i.source == key)}
                    for key, label in Invoice.SOURCE_CHOICES
                ],
                "collected": sum(i.net_total for i in settled),
                "outstanding": sum(i.total for i in outstanding),
                "outstanding_count": len(outstanding),
                "recent": [
                    {"id": i.id, "code": i.code, "date": i.date, "source": i.source, "status": i.status, "total": i.total}
                    for i in sorted(live, key=lambda i: (i.date, i.id), reverse=True)[:STORE_RECENT_LIMIT]
                ],
            }

        rentals = {"restricted": True}
        if user.has_perm_code("rentals.view"):
            assets = RentalAsset.objects.filter(Q(source_stock_point=sp) | Q(returned_to=sp)).order_by("asset_tag")
            rentals = {
                "restricted": False,
                "assets": [
                    {"id": a.id, "asset_tag": a.asset_tag, "brand": a.brand, "model_name": a.model_name,
                     "status": a.status, "status_label": a.get_status_display(),
                     "from_here": a.source_stock_point_id == sp.id, "returned_here": a.returned_to_id == sp.id}
                    for a in assets
                ],
            }

        # Staff whose Store Location is this store (accounts.User.stock_point,
        # set by the Owner) -- name, role and active status only.
        staff = User.objects.filter(stock_point=sp).select_related("role").order_by("-is_active", "first_name", "username")

        return Response({
            "stock_point": StockPointSerializer(sp, context={"request": request}).data,
            "staff": [
                {"id": u.id, "name": u.get_full_name() or u.username, "username": u.username,
                 "role": u.role.label if u.role_id else None, "is_active": u.is_active}
                for u in staff
            ],
            "stock": StoreStockRowSerializer(stock, many=True).data,
            "parts": [
                {"id": ps.id, "part_id": ps.part_id, "slug": ps.part.slug, "name": ps.part.name,
                 "compatible_brands": ps.part.compatible_brands, "quantity": ps.quantity}
                for ps in parts
            ],
            "repairs": repairs,
            "invoices": invoices,
            "rentals": rentals,
        })


class ProductViewSet(viewsets.ModelViewSet):
    # The catalogue itself is shared; get_queryset() swaps this prefetch for
    # one that only nests the requesting account's own store stock.
    queryset = Product.objects.prefetch_related("variants__stock__stock_point").all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "lookup": None, "serials": None, "low_stock": None,
        "create": "inventory.edit", "update": "inventory.edit",
        "partial_update": "inventory.edit", "destroy": "inventory.edit",
    }

    def get_queryset(self):
        qs = product_queryset(self.request.user)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            # a serial number finds its product only through the account's own store's units
            scope = StoreScope(self.request.user)
            serial = Q(variants__serials__serial_number__icontains=q)
            if not scope.all:
                serial &= Q(variants__serials__stock_point_id=scope.store_id)
            qs = qs.filter(
                Q(brand__icontains=q) | Q(model_name__icontains=q)
                | Q(product_code__icontains=q) | Q(variants__code__icontains=q) | serial
            ).distinct()
        return qs

    def _refuse_shared_product(self, product, verb):
        # A product's name, codes and deletion reach every store that stocks
        # it, so store staff may only change one no other store holds.
        scope = StoreScope(self.request.user)
        if scope.owner:
            return
        scope.require_assigned()
        if Stock.objects.filter(variant__product=product).exclude(stock_point_id=scope.store_id).exists():
            raise PermissionDenied(f"This product is also stocked at another store, so only the Owner can {verb} it.")

    def perform_create(self, serializer):
        StoreScope(self.request.user).require_assigned()
        serializer.save()

    def perform_update(self, serializer):
        self._refuse_shared_product(serializer.instance, "edit")
        serializer.save()

    def perform_destroy(self, instance):
        self._refuse_shared_product(instance, "delete")
        instance.delete()

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        # Totals here cover only the requesting account's own store stock.
        if not StoreScope(request.user).assigned:
            return Response([])
        items = []
        for p in self.get_queryset():
            for v in p.variants.all():
                if v.total_stock <= LOW_STOCK_THRESHOLD:
                    items.append({
                        "product": ProductSerializer(p).data["display_name"],
                        "variant_code": v.code, "spec": v.spec, "total_stock": v.total_stock,
                    })
        return Response(items)

    @action(detail=True, methods=["get"])
    def serials(self, request, pk=None):
        """The serial-numbered units of this product the account's store(s)
        hold -- each one's own serial number, under the product's one
        Product ID and HSN."""
        product = self.get_object()
        rows = (StoreScope(request.user).filter(StockSerial.objects.filter(variant__product=product), "stock_point")
                .select_related("variant", "stock_point").order_by("variant__code", "serial_number"))
        return Response({
            "product_code": product.product_code, "hsn": product.hsn,
            "serials": [{
                "id": s.id, "serial_number": s.serial_number, "variant": s.variant.code, "spec": s.variant.spec, "colour": s.variant.colour,
                "stock_point": s.stock_point.name, "received_at": s.received_at,
                "status": s.status, "status_label": s.get_status_display(),
                "invoice": s.invoice_item.invoice.code if s.invoice_item_id else None,
                "customer": s.invoice_item.invoice.party.name if s.invoice_item_id else None,
            } for s in rows.select_related("invoice_item__invoice__party")],
        })

    @action(detail=False, methods=["get"])
    def lookup(self, request):
        """
        Barcode/scanner lookup -- a Bluetooth scanner types the code
        into whatever field has focus and hits Enter, so the frontend
        just needs to fire this on Enter with whatever text landed in
        the scan box. Matches either a product's own code or any of
        its variant codes.
        """
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response({"detail": "code is required"}, status=400)
        products = product_queryset(request.user)
        product = (
            products.filter(product_code__iexact=code).first()
            or products.filter(variants__code__iexact=code).first()
        )
        if not product:
            return Response({"detail": "No product or variant matches that code."}, status=404)
        return Response(ProductSerializer(product).data)


class PartViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Part.objects.all()
    serializer_class = PartSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    def get_queryset(self):
        return super().get_queryset().prefetch_related(part_stock_prefetch(StoreScope(self.request.user)))


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """The Hardware/Software work catalogue used to build a repair ticket."""
    queryset = Service.objects.select_related("part").all()
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    def get_queryset(self):
        # the nested part carries its stock -- only this account's store's rows
        return super().get_queryset().prefetch_related(part_stock_prefetch(StoreScope(self.request.user), "part__stock"))


DEFAULT_SPEC = "Standard"


def _int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_variant(product, data):
    """
    Which variant a restock goes to. Stock is kept per variant, but a
    product doesn't have to be set up with variants:
      - `variant` given             -> that variant
      - `spec` given                -> a new variant with that spec
      - neither, product has one    -> its only variant
      - neither, product has none   -> a default "Standard" variant,
                                       created now (price optional)
      - neither, product has several -> ask which one
    Returns (variant, created, error_message).
    """
    variant_id = data.get("variant")
    if variant_id:
        variant = Variant.objects.filter(pk=variant_id, product=product).first()
        if variant is None:
            return None, False, "That variant doesn't belong to this product."
        return variant, False, None

    spec = (data.get("spec") or "").strip()
    sell_price = _int_or_zero(data.get("sell_price"))
    if not spec:
        existing = list(product.variants.all()[:2])
        if len(existing) == 1:
            return existing[0], False, None
        if len(existing) > 1:
            return None, False, "This product has several variants -- pick which one the stock is for."
        spec = DEFAULT_SPEC
    elif sell_price <= 0:
        return None, False, "sell_price must be a positive number for a new variant."

    sell_price = max(sell_price, 0)
    mrp = _int_or_zero(data.get("mrp")) or sell_price
    cost = _int_or_zero(data.get("cost")) or round(sell_price * 0.78)
    variant = Variant.objects.create(
        product=product, spec=spec, mrp=mrp, sell_price=sell_price, cost=cost,
        code=next_code("VC-SKU", Variant, "code"),
    )
    return variant, True, None


class AddStockView(APIView):
    """
    One endpoint for both real-world restock flows:
      - an existing product/variant getting more units in at a shop
        (pass `product` + `variant`), or
      - a brand-new item arriving that isn't in the catalogue yet
        (pass `brand`/`model_name`/... instead of `product`, and
        optionally `spec`/`sell_price`/... instead of `variant`).
    Variants are optional -- see _resolve_variant() for how a restock
    without one is placed.
    Whichever product code / variant code isn't supplied gets
    auto-generated -- this is the "no HSN, no scanner code yet"
    case: the item still gets a unique internal code so it's never
    untracked, ready to be put on a printed label.

    With `category` (and no `product`) it's the Add stock -> New product
    form instead: category specifications, one variant built from them and
    optional serial numbers per unit; with `entry: "existing"` it's the
    Existing product form (a chosen variant, or a new colour / spec of the
    product) -- see catalog.new_product.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    @transaction.atomic
    def post(self, request):
        data = request.data
        scope = StoreScope(request.user)
        scope.require_assigned()
        # only the account's own store -- any other id is simply not found
        stock_point = get_object_or_404(scope.filter(StockPoint.objects.all(), "id"), pk=data.get("stock_point"))
        require_active(stock_point, "stock")
        if data.get("entry") == "existing":
            return self._existing_product(request, stock_point)
        if data.get("category") and not data.get("product"):
            return self._new_product(request, stock_point)
        try:
            quantity = int(data.get("quantity", 0))
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            return Response({"detail": "Quantity must be a positive number."}, status=400)

        generated_product_code = False
        product_id = data.get("product")
        if product_id:
            product = get_object_or_404(Product, pk=product_id)
        else:
            model_name = (data.get("model_name") or "").strip()
            if not model_name:
                return Response({"detail": "model_name is required for a new product."}, status=400)
            brand = (data.get("brand") or "").strip()
            hsn = (data.get("hsn") or "").strip()
            prefix = "VC-LAP" if brand and brand != "\u2014" else "VC-ACC"
            product = Product.objects.create(
                brand=brand or "\u2014", model_name=model_name,
                processor=(data.get("processor") or "").strip(),
                hsn=hsn, condition=(data.get("condition") or "New").strip(),
                product_code=next_code(prefix, Product, "product_code"),
            )
            generated_product_code = True

        variant, generated_variant_code, error = _resolve_variant(product, data)
        if error:
            # don't keep a product created above for a request that failed
            transaction.set_rollback(True)
            return Response({"detail": error}, status=400)

        stock, _ = Stock.objects.get_or_create(variant=variant, stock_point=stock_point, defaults={"quantity": 0})
        update = {"quantity": F("quantity") + quantity}
        # Optional: where the units were put away. Left blank, the row
        # keeps whatever location it already had.
        location = (data.get("location") or "").strip()[:80]
        if location:
            update["location"] = location
        before = stock.quantity
        Stock.objects.filter(pk=stock.pk).update(**update)
        stock.refresh_from_db()
        # QuerySet.update() fires no model signals -- describe the movement for Activity Logs
        activity.note(stock, "add-stock",
                      f"Added {quantity} × {product.display_name} ({variant.spec or variant.code}) to stock at {stock_point.name}",
                      changes={"quantity": (before, stock.quantity)})

        # re-read through the scoped prefetch so the reply nests only this store's stock
        product = product_queryset(request.user).get(pk=product.pk)
        variant = next(v for v in product.variants.all() if v.pk == variant.pk)
        return Response({
            "product": ProductSerializer(product).data,
            "variant": VariantSerializer(variant).data,
            "stock_point": stock_point.name,
            "new_quantity": stock.quantity,
            "location": stock.location,
            "generated_product_code": generated_product_code,
            "generated_variant_code": generated_variant_code,
        }, status=201)


    def _new_product(self, request, stock_point):
        serializer = new_product.NewProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # the view's transaction: a failure anywhere leaves no product, stock or serials
        product, variant, stock, serials = new_product.create(data, request.user, stock_point)
        activity.note(stock, "add-stock",
                      f"Added new product {product.display_name} ({variant.spec}): {stock.quantity} unit(s) at {stock_point.name}, "
                      f"serial numbers {serials[0]}{f' … {serials[-1]}' if len(serials) > 1 else ''}",
                      changes={"quantity": (0, stock.quantity)})
        product = product_queryset(request.user).get(pk=product.pk)
        variant = next(v for v in product.variants.all() if v.pk == variant.pk)
        return Response({
            "product": ProductSerializer(product).data,
            "variant": VariantSerializer(variant).data,
            "stock_point": stock_point.name,
            "new_quantity": stock.quantity,
            "location": stock.location,
            "serials": serials,
            "serials_recorded": len(serials),
            "generated_product_code": True,
            "generated_variant_code": True,
        }, status=201)

    def _existing_product(self, request, stock_point):
        serializer = new_product.ExistingStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product, variant, stock, before, created, changes, serials = new_product.add_existing(data, request.user, stock_point)
        what = f"new variant {variant.code} ({variant.spec}{f', {variant.colour}' if variant.colour else ''})" if created else f"{variant.code}"
        activity.note(stock, "add-stock",
                      f"Added {data['quantity']} × {product.display_name} {what} to stock at {stock_point.name}, "
                      f"serial numbers {serials[0]}{f' … {serials[-1]}' if len(serials) > 1 else ''}",
                      changes={"quantity": (before, stock.quantity), **changes})
        product = product_queryset(request.user).get(pk=product.pk)
        variant = next(v for v in product.variants.all() if v.pk == variant.pk)
        return Response({
            "product": ProductSerializer(product).data,
            "variant": VariantSerializer(variant).data,
            "stock_point": stock_point.name,
            "previous_quantity": before,
            "new_quantity": stock.quantity,
            "location": stock.location,
            "created_variant": created,
            "price_changes": {k: list(v) for k, v in changes.items() if k != "hsn"},
            "hsn_updated": "hsn" in changes,
            "serials": serials,
            "serials_recorded": len(serials),
            "generated_product_code": False,
            "generated_variant_code": created,
        }, status=201)


class StockLocationView(APIView):
    """
    Set or clear where one variant's units sit inside one shop
    (PATCH {"location": "Rack A / Shelf 3"}). Separate from add-stock so
    staff can re-shelve items without recording a fake restock.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def patch(self, request, pk):
        stocks = StoreScope(request.user).filter(Stock.objects.select_related("stock_point"), "stock_point")
        stock = get_object_or_404(stocks, pk=pk)
        location = request.data.get("location")
        if location is None:
            return Response({"detail": "location is required (send an empty string to clear it)."}, status=400)
        location = str(location).strip()
        if len(location) > 80:
            return Response({"detail": "location must be 80 characters or fewer."}, status=400)
        stock.location = location
        stock.save(update_fields=["location"])
        return Response(StockSerializer(stock).data)



class StockSerialViewSet(StoreScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    Serial-numbered units (catalog.serials). List: ?variant=&stock_point=&status=.
    available: the units a sale can pick at one store. trace: a unit's whole
    life by its serial number. write_off: close a unit no longer on the shelf.
    """
    store_lookups = ("stock_point",)
    store_payload_field = None
    queryset = StockSerial.objects.select_related("variant__product", "stock_point", "invoice_item__invoice__party").all()
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "head", "options"]  # POST only for write_off; serials are made by Add stock
    required_perms = {"list": None, "retrieve": None, "available": None, "trace": None, "write_off": "inventory.edit"}

    @staticmethod
    def _row(s):
        return {"id": s.id, "serial_number": s.serial_number, "status": s.status, "status_label": s.get_status_display(),
                "variant": s.variant_id, "variant_code": s.variant.code, "product": s.variant.product.display_name,
                "spec": s.variant.spec, "stock_point": s.stock_point.name, "received_at": s.received_at,
                "invoice": s.invoice_item.invoice.code if s.invoice_item_id else None}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        for key in ("variant", "stock_point"):
            if p.get(key):
                qs = qs.filter(**{f"{key}_id": p[key]})
        if p.get("status") in dict(StockSerial.STATUS_CHOICES):
            qs = qs.filter(status=p["status"])
        return qs.order_by("serial_number")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        rows = [self._row(s) for s in (page if page is not None else self.get_queryset())]
        return self.get_paginated_response(rows) if page is not None else Response(rows)

    def retrieve(self, request, *args, **kwargs):
        return Response(self._row(self.get_object()))

    @action(detail=False, methods=["get"])
    def available(self, request):
        """In-stock units of one variant at one store, for the sale invoice picker."""
        from . import serials as serial_tracking

        variant = Variant.objects.select_related("product").filter(pk=request.query_params.get("variant")).first()
        stock_point = StockPoint.objects.filter(pk=request.query_params.get("stock_point")).first()
        if not variant or not stock_point:
            raise ValidationError({"detail": "variant and stock_point are required."})
        if not self.store_scope.allows(stock_point.id):
            raise PermissionDenied("That store isn't yours.")
        if not serial_tracking.tracked(variant):
            return Response({"tracked": False, "serials": [], "untracked": 0})
        rows = serial_tracking.in_stock_qs(variant, stock_point).order_by("serial_number")
        return Response({"tracked": True, "serials": [s.serial_number for s in rows],
                         "untracked": serial_tracking.untracked_units(variant, stock_point)})

    @action(detail=False, methods=["get"])
    def trace(self, request):
        """Everything about one unit: where it is, who bought it, warranty, repairs, every step."""
        from . import serials as serial_tracking

        q = (request.query_params.get("q") or "").strip()
        if not q:
            raise ValidationError({"q": "Enter or scan a serial number."})
        serial = self.get_queryset().filter(serial_number__iexact=q).first()
        if not serial:
            # a unit sold from / moved to another store is still traceable by its own store's staff via history
            serial = StockSerial.objects.filter(serial_number__iexact=q, events__stock_point_id=self.store_scope.store_id).first() \
                if not self.store_scope.all and self.store_scope.store_id else None
        if not serial:
            return Response({"detail": f"No unit with serial number {q} found."}, status=404)
        return Response(serial_tracking.trace(serial))

    @action(detail=True, methods=["post"])
    def write_off(self, request, pk=None):
        from . import serials as serial_tracking

        reduce_stock = request.data.get("reduce_stock") in (True, "true", "1", 1)
        serial = serial_tracking.write_off(self.get_object(), request.user, request.data.get("reason"), reduce_stock)
        return Response(self._row(serial))
