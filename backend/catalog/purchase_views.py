"""
Suppliers' purchase history, tagging stock already held, and the supplier
profit comparison (catalog.purchases).

Purchase prices are cost data: the history and tagging need inventory.edit
(the staff who add stock and see costs already); the comparison is part of
Profit & Loss, so it follows that permission and store scope.
"""
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import activity
from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope
from parties.models import Party

from . import purchases
from .models import StockSerial, Variant


class SupplierHistoryView(APIView):
    """GET /api/purchases/supplier/<party id>/ -- what was bought from them and what it earned."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def get(self, request, pk):
        supplier = get_object_or_404(Party, pk=pk)
        return Response({**purchases.history(supplier), "can_pay": CanPaySuppliers().has_permission(request, self)})


class CanPaySuppliers(permissions.BasePermission):
    """Money out of the cash / bank book: the same people who pay expenses."""
    message = "Your role can't record payments to suppliers."

    def has_permission(self, request, view):
        from accounting.expenses import can_manage_expenses

        user = request.user
        return bool(user and user.is_authenticated and (user.is_superuser or can_manage_expenses(user)))


class SupplierPayView(APIView):
    """POST /api/purchases/supplier/<party id>/pay/ -- record money paid to a supplier (posts to the cash / bank book)."""
    permission_classes = [permissions.IsAuthenticated, CanPaySuppliers]

    def post(self, request, pk):
        supplier = get_object_or_404(Party, pk=pk, type=Party.SUPPLIER)
        payload = purchases.PaySerializer(data=request.data, context={"supplier": supplier})
        payload.is_valid(raise_exception=True)
        payment = purchases.pay(supplier, payload.validated_data, request.user)
        activity.note(payment, "supplier-paid", f"₹{payment.amount:,} paid to {supplier.name} by {payment.method}")
        return Response(purchases.history(supplier), status=201)


class TagStockView(APIView):
    """POST /api/purchases/tag/ -- put stock already held (or sold) on a supplier's bill."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def post(self, request):
        payload = purchases.TagSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        purchase = purchases.tag(payload.validated_data, request.user)
        activity.note(purchase, "purchase-tagged",
                      f"{purchase.qty} × {purchase.variant.product.display_name} ({purchase.variant.spec}) put on "
                      f"{purchase.supplier.name}'s bill{f' {purchase.bill_no}' if purchase.bill_no else ''} at ₹{purchase.unit_cost:,} each")
        return Response({"id": purchase.id, "qty": purchase.qty, "supplier": purchase.supplier.name}, status=201)


class UntaggedUnitsView(APIView):
    """GET /api/purchases/untagged/?variant=<id> -- this product's units with no supplier yet (any status)."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def get(self, request):
        variant = get_object_or_404(Variant, pk=request.query_params.get("variant") or 0)
        units = (StockSerial.objects.filter(variant=variant, purchase__isnull=True)
                 .select_related("stock_point").order_by("status", "serial_number"))
        scope = StoreScope(request.user)
        if not scope.all:
            units = units.filter(stock_point_id=scope.store_id)
        return Response([{"serial_number": u.serial_number, "status": u.status, "status_label": u.get_status_display(),
                          "store": u.stock_point.name} for u in units[:500]])


class SupplierComparisonView(APIView):
    """GET /api/reports/supplier-comparison/ -- which supplier's units earn more, product by product."""
    from reports.profit_loss import CanViewProfitLoss

    permission_classes = [permissions.IsAuthenticated, CanViewProfitLoss]

    def get(self, request):
        scope = StoreScope(request.user)
        return Response(purchases.comparison(None if scope.all else [scope.store_id]))
