from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm, IsStaffAccount
from .models import Part, Product, Service, Stock, StockPoint, Variant
from .serializers import (
    PartSerializer, ProductSerializer, ServiceSerializer, StockPointSerializer, VariantSerializer,
)
from .utils import next_code


class StockPointViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockPoint.objects.all()
    serializer_class = StockPointSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.prefetch_related("variants__stock__stock_point").all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "lookup": None,
        "create": "inventory.edit", "update": "inventory.edit",
        "partial_update": "inventory.edit", "destroy": "inventory.edit",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(brand__icontains=q) | Q(model_name__icontains=q)
                | Q(product_code__icontains=q) | Q(variants__code__icontains=q)
            ).distinct()
        return qs

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        items = []
        for p in self.get_queryset():
            for v in p.variants.all():
                if v.total_stock <= 4:
                    items.append({
                        "product": ProductSerializer(p).data["display_name"],
                        "variant_code": v.code, "spec": v.spec, "total_stock": v.total_stock,
                    })
        return Response(items)

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
        product = (
            Product.objects.filter(product_code__iexact=code).first()
            or Product.objects.filter(variants__code__iexact=code).first()
        )
        if not product:
            return Response({"detail": "No product or variant matches that code."}, status=404)
        return Response(ProductSerializer(product).data)


class PartViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Part.objects.prefetch_related("stock__stock_point").all()
    serializer_class = PartSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """The Hardware/Software work catalogue used to build a repair ticket."""
    queryset = Service.objects.select_related("part").all()
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]


class AddStockView(APIView):
    """
    One endpoint for both real-world restock flows:
      - an existing product/variant getting more units in at a shop
        (pass `product` + `variant`), or
      - a brand-new item arriving that isn't in the catalogue yet
        (pass `brand`/`model_name`/... instead of `product`, and
        `spec`/`sell_price`/... instead of `variant`).
    Whichever product code / variant code isn't supplied gets
    auto-generated -- this is the "no HSN, no scanner code yet"
    case: the item still gets a unique internal code so it's never
    untracked, ready to be put on a printed label.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def post(self, request):
        data = request.data
        stock_point = get_object_or_404(StockPoint, pk=data.get("stock_point"))
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

        generated_variant_code = False
        variant_id = data.get("variant")
        if variant_id:
            variant = get_object_or_404(Variant, pk=variant_id, product=product)
        else:
            spec = (data.get("spec") or "").strip()
            if not spec:
                return Response({"detail": "spec is required for a new variant."}, status=400)
            try:
                sell_price = int(data.get("sell_price", 0))
            except (TypeError, ValueError):
                sell_price = 0
            if sell_price <= 0:
                return Response({"detail": "sell_price must be a positive number for a new variant."}, status=400)
            mrp = int(data.get("mrp") or sell_price)
            cost = int(data.get("cost") or round(sell_price * 0.78))
            variant = Variant.objects.create(
                product=product, spec=spec, mrp=mrp, sell_price=sell_price, cost=cost,
                code=next_code("VC-SKU", Variant, "code"),
            )
            generated_variant_code = True

        stock, _ = Stock.objects.get_or_create(variant=variant, stock_point=stock_point, defaults={"quantity": 0})
        Stock.objects.filter(pk=stock.pk).update(quantity=F("quantity") + quantity)
        stock.refresh_from_db()

        return Response({
            "product": ProductSerializer(product).data,
            "variant": VariantSerializer(variant).data,
            "stock_point": stock_point.name,
            "new_quantity": stock.quantity,
            "generated_product_code": generated_product_code,
            "generated_variant_code": generated_variant_code,
        }, status=201)
