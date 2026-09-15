from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from parties.models import Message, Party
from repairs.models import RepairTicket
from sales.models import Invoice
from .models import Warranty
from .serializers import WarrantySerializer


class WarrantyViewSet(viewsets.ModelViewSet):
    queryset = Warranty.objects.select_related("party", "invoice", "repair_ticket").all()
    serializer_class = WarrantySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "eligible_items": None,
        "create": "warranty.manage", "update": "warranty.manage",
        "partial_update": "warranty.manage", "destroy": "warranty.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        phone = self.request.query_params.get("phone")
        q = self.request.query_params.get("q")
        section = self.request.query_params.get("section")
        invoice_id = self.request.query_params.get("invoice")
        if phone:
            qs = qs.filter(party__phone__icontains=phone)
        if q:
            qs = qs.filter(party__name__icontains=q)
        if section:
            qs = qs.filter(section=section)
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)
        return qs

    def perform_create(self, serializer):
        warranty = serializer.save()
        # "mailed to the customer" -- logged as an outbound email on the
        # party's own thread, same as every other notification in the
        # app (repairs, broadcast). No live SMTP provider is wired up
        # yet; swap this for a real send when one is.
        subject_line = f"Your warranty on {warranty.item_label}"
        body = (
            f"{subject_line}\n\n"
            f"Covers: {warranty.item_label}\n"
            f"Valid: {warranty.start_date:%d %b %Y} to {warranty.end_date:%d %b %Y}\n\n"
            f"{warranty.terms_text}"
        )
        Message.objects.create(party=warranty.party, channel=Message.EMAIL, direction=Message.OUT, body=body)

    @action(detail=False, methods=["get"], url_path="eligible-items")
    def eligible_items(self, request):
        """
        What this customer can actually have a warranty raised
        against right now -- feeds the "New warranty" form so staff
        can only pick transactions that meet the condition (paid
        invoice / delivered repair) instead of typing one in free-hand.
        """
        party_id = request.query_params.get("party")
        if not party_id:
            return Response({"detail": "party is required"}, status=400)
        party = Party.objects.filter(pk=party_id).first()
        if not party:
            return Response({"detail": "No such party."}, status=404)

        covered_invoice_ids = set(Warranty.objects.filter(section=Warranty.SALES, invoice__party=party).values_list("invoice_id", flat=True))
        covered_ticket_ids = set(Warranty.objects.filter(section=Warranty.REPAIR, repair_ticket__party=party).values_list("repair_ticket_id", flat=True))

        invoices = []
        for inv in Invoice.objects.filter(party=party, status=Invoice.PAID).prefetch_related("items__variant__product"):
            if inv.id in covered_invoice_ids:
                continue
            names = ", ".join(i.variant.product.display_name for i in inv.items.all())
            invoices.append({"id": inv.id, "code": inv.code, "label": f"{inv.code} \u2014 {names}", "date": inv.date})

        tickets = []
        for t in RepairTicket.objects.filter(party=party).prefetch_related("invoices"):
            inv = t.original_invoice
            if not inv or t.id in covered_ticket_ids:
                continue
            tickets.append({"id": t.id, "code": t.code, "label": f"{t.code} \u2014 {t.brand} {t.model_name}", "date": inv.date})

        return Response({"invoices": invoices, "repair_tickets": tickets})
