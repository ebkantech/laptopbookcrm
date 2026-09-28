from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from crmbook_backend.notify import notify_staff
from .models import Invoice
from .serializers import InvoiceSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related("party", "stock_point").prefetch_related("items__variant__product").all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "invoices.view", "retrieve": "invoices.view",
        "create": "invoices.create", "update": "invoices.create",
        "partial_update": "invoices.create", "destroy": "invoices.create",
        "settle": "invoices.settle",
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
        invoice = self.get_object()
        invoice.status = Invoice.PAID
        invoice.save(update_fields=["status"])
        # Task 2 wiring: "any payment done" -- who actually gets pinged is
        # configured on Settings > Staff alerts, not hardcoded here.
        notify_staff(
            "payment_received",
            f"Invoice {invoice.code} settled",
            f"Invoice {invoice.code} for {invoice.party.name} was marked paid -- ₹{invoice.total}.",
        )
        return Response(InvoiceSerializer(invoice).data)
