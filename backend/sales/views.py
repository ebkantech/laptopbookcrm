from datetime import date

from django.conf import settings
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from crmbook_backend.notify import notify_staff
from .models import PAYMENT_METHODS, Invoice
from .serializers import InvoiceSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related("party", "stock_point", "settled_by").prefetch_related("items__variant__product").all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "invoices.view", "retrieve": "invoices.view",
        "create": "invoices.create", "update": "invoices.create",
        "partial_update": "invoices.create", "destroy": "invoices.create",
        "settle": "invoices.settle",
        "print_data": "invoices.view",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        party = self.request.query_params.get("party")
        if status:
            qs = qs.filter(status=status)
        if party:
            qs = qs.filter(party_id=party)
        return qs

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """
        Record a payment received outside any gateway: how it was paid,
        the reference to match against the bank/UPI statement, and when.
        Body: {"pay_method": "UPI", "payment_reference": "UTR 4123...",
        "paid_on": "2026-10-03"} -- paid_on defaults to today. A reference
        is required for every method except cash.
        """
        invoice = self.get_object()
        if invoice.status == Invoice.PAID:
            return Response({"detail": "This invoice is already marked paid."}, status=400)
        method = (request.data.get("pay_method") or "").strip()
        reference = (request.data.get("payment_reference") or "").strip()
        if method not in PAYMENT_METHODS:
            return Response({"detail": f"pay_method must be one of: {', '.join(PAYMENT_METHODS)}."}, status=400)
        if method != "Cash" and not reference:
            return Response({"detail": "Enter the payment reference (UPI/UTR, cheque or card transaction number)."}, status=400)
        if len(reference) > 80:
            return Response({"detail": "payment_reference must be 80 characters or fewer."}, status=400)
        try:
            paid_on = date.fromisoformat(request.data["paid_on"]) if request.data.get("paid_on") else date.today()
        except (TypeError, ValueError):
            return Response({"detail": "paid_on must be a date (YYYY-MM-DD)."}, status=400)
        if paid_on > date.today():
            return Response({"detail": "paid_on can't be in the future."}, status=400)

        invoice.status = Invoice.PAID
        invoice.pay_method = method
        invoice.payment_reference = reference
        invoice.paid_on = paid_on
        invoice.settled_by = request.user
        invoice.save(update_fields=["status", "pay_method", "payment_reference", "paid_on", "settled_by"])
        # Task 2 wiring: "any payment done" -- who actually gets pinged is
        # configured on Settings > Staff alerts, not hardcoded here.
        notify_staff(
            "payment_received",
            f"Invoice {invoice.code} settled",
            f"Invoice {invoice.code} for {invoice.party.name} was marked paid -- ₹{invoice.total}.",
        )
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["get"], url_path="print-data")
    def print_data(self, request, pk=None):
        """Everything the printable invoice needs in one call: seller and
        branch details, buyer details, and line items with HSN."""
        invoice = self.get_object()
        sp, party = invoice.stock_point, invoice.party
        items = []
        for n, item in enumerate(invoice.items.all(), start=1):
            variant = item.variant
            items.append({
                "n": n,
                "description": variant.product.display_name,
                "spec": variant.spec,
                "code": variant.code,
                "hsn": variant.product.hsn,
                "qty": item.qty,
                "rate": item.price,
                "amount": item.qty * item.price,
            })
        return Response({
            "invoice": InvoiceSerializer(invoice).data,
            "seller": {
                "name": settings.BUSINESS_NAME,
                "branch": sp.name,
                "address": sp.address,
                "phone": sp.phone or settings.BUSINESS_PHONE,
                "email": settings.BUSINESS_EMAIL,
                "gstin": sp.gstin or settings.BUSINESS_GSTIN,
            },
            "buyer": {
                "name": party.name, "phone": party.phone, "email": party.email,
                "gstin": party.gstin, "city": party.city,
            },
            "items": items,
            "total_qty": sum(i["qty"] for i in items),
            "total": sum(i["amount"] for i in items),
        })
