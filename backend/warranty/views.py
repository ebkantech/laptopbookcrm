from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import HasPerm
from accounts.store_scope import StoreScopedMixin
from crmbook_backend.notify import send_email
from parties.models import Message, Party
from repairs.models import RepairTicket
from sales.models import Invoice
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import services
from .models import Warranty, WarrantyClaim
from .serializers import WarrantyClaimSerializer, WarrantySerializer


class WarrantyViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    # Store scope: the sale invoice or repair ticket the warranty covers.
    # A warranty with neither has no store and stays Owner-only.
    store_lookups = ("invoice__stock_point", "repair_ticket__stock_point")
    store_payload_field = None
    queryset = Warranty.objects.select_related("party", "invoice", "repair_ticket").prefetch_related("claims").all()
    serializer_class = WarrantySerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "eligible_items": None,
        "create": "warranty.manage", "update": "warranty.manage",
        "partial_update": "warranty.manage", "destroy": "warranty.manage",
        "summary": None, "expiring": None, "remind": "warranty.manage", "send_reminders": "warranty.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        phone = self.request.query_params.get("phone")
        q = self.request.query_params.get("q")
        section = self.request.query_params.get("section")
        invoice_id = self.request.query_params.get("invoice")
        serial = (self.request.query_params.get("serial") or "").strip()
        if serial:
            qs = qs.filter(invoice__items__serials__serial_number__iexact=serial).distinct()
        if phone:
            qs = qs.filter(party__phone__icontains=phone)
        if q:
            qs = qs.filter(party__name__icontains=q)
        if section:
            qs = qs.filter(section=section)
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)
        return qs

    def _check_covered_record(self, serializer):
        scope = self.store_scope
        invoice = serializer.validated_data.get("invoice")
        ticket = serializer.validated_data.get("repair_ticket")
        if invoice is not None and not scope.allows(invoice.stock_point_id):
            raise ValidationError({"invoice": "That invoice isn't from your store."})
        if ticket is not None and not scope.allows(ticket.stock_point_id):
            raise ValidationError({"repair_ticket": "That repair ticket isn't from your store."})

    def perform_update(self, serializer):
        self._check_covered_record(serializer)
        serializer.save()

    def perform_create(self, serializer):
        self._check_covered_record(serializer)
        warranty = serializer.save()
        services.announce(warranty)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Numbers for the strip above the list (store-scoped)."""
        today = timezone.localdate()
        qs = self.store_scope.filter(Warranty.objects.all(), *self.store_lookups, distinct=True)
        claims = WarrantyClaim.objects.filter(warranty__in=qs)
        month = claims.filter(created_at__year=today.year, created_at__month=today.month)
        return Response({
            "active": qs.filter(end_date__gt=today + timedelta(days=services.EXPIRING_DAYS)).count(),
            "expiring": qs.filter(end_date__gte=today, end_date__lte=today + timedelta(days=services.EXPIRING_DAYS)).count(),
            "expired": qs.filter(end_date__lt=today).count(),
            "open_claims": claims.filter(status__in=(WarrantyClaim.OPEN, WarrantyClaim.APPROVED)).count(),
            "claims_this_month": month.count(),
            "claim_cost_this_month": month.filter(status=WarrantyClaim.RESOLVED).aggregate(t=Sum("cost"))["t"] or 0,
        })

    @action(detail=False, methods=["get"])
    def expiring(self, request):
        """Warranties ending soonest -- the calling list. ?days=30 (default)."""
        try:
            days = max(1, min(int(request.query_params.get("days", services.EXPIRING_DAYS)), 365))
        except ValueError:
            days = services.EXPIRING_DAYS
        today = timezone.localdate()
        qs = self.get_queryset().filter(end_date__gte=today, end_date__lte=today + timedelta(days=days)).order_by("end_date")
        return Response(WarrantySerializer(qs, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def remind(self, request, pk=None):
        """Send this customer the 'warranty ending' reminder now."""
        w = self.get_object()
        if w.status == "Expired":
            raise ValidationError({"detail": "This warranty has already ended."})
        services.remind(w)
        now = timezone.now()
        w.reminded_7_at = now if (w.end_date - timezone.localdate()).days <= services.FINAL_DAYS else w.reminded_7_at
        w.reminded_30_at = w.reminded_30_at or now
        w.save(update_fields=["reminded_30_at", "reminded_7_at"])
        return Response(WarrantySerializer(w, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["post"])
    def send_reminders(self, request):
        """Send every due reminder (the 30-day and 7-day ones not yet sent) -- same as the daily command."""
        return Response({"sent": services.send_due_reminders()})

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
        scope = self.store_scope
        sale_invoices = scope.filter(Invoice.objects.filter(party=party, status=Invoice.PAID, source=Invoice.SALE), "stock_point")
        for inv in sale_invoices.prefetch_related("items__variant__product"):
            if inv.id in covered_invoice_ids:
                continue
            names = ", ".join(i.label for i in inv.items.all())
            invoices.append({"id": inv.id, "code": inv.code, "label": f"{inv.code} \u2014 {names}", "date": inv.date})

        tickets = []
        for t in scope.filter(RepairTicket.objects.filter(party=party), "stock_point").prefetch_related("invoices"):
            inv = t.original_invoice
            if not inv or t.id in covered_ticket_ids:
                continue
            tickets.append({"id": t.id, "code": t.code, "label": f"{t.code} \u2014 {t.brand} {t.model_name}", "date": inv.date})

        return Response({"invoices": invoices, "repair_tickets": tickets})


class WarrantyClaimViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    """Claims made under warranties. Staff with warranty.manage raise, decide and resolve them."""
    store_lookups = ("warranty__invoice__stock_point", "warranty__repair_ticket__stock_point")
    store_payload_field = None
    store_distinct = True
    queryset = WarrantyClaim.objects.select_related("warranty__party", "repair_ticket", "raised_by", "decided_by").all()
    serializer_class = WarrantyClaimSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "head", "options"]
    required_perms = {"list": None, "retrieve": None, "create": "warranty.manage", "decide": "warranty.manage", "resolve": "warranty.manage"}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status") in dict(WarrantyClaim.STATUS_CHOICES):
            qs = qs.filter(status=p["status"])
        elif p.get("group") == "open":
            qs = qs.filter(status__in=(WarrantyClaim.OPEN, WarrantyClaim.APPROVED))
        if p.get("warranty"):
            qs = qs.filter(warranty_id=p["warranty"])
        return qs

    def _ticket(self, code, party_id):
        code = (code or "").strip()
        if not code:
            return None
        ticket = self.store_scope.filter(RepairTicket.objects.filter(code__iexact=code), "stock_point").first()
        if not ticket or ticket.party_id != party_id:
            raise ValidationError({"repair_code": "No repair job with that code for this customer."})
        return ticket

    def create(self, request, *args, **kwargs):
        warranty = Warranty.objects.filter(pk=request.data.get("warranty")).first()
        if not warranty or not self.store_scope.filter(Warranty.objects.filter(pk=warranty.pk), "invoice__stock_point", "repair_ticket__stock_point").exists():
            raise ValidationError({"warranty": "Pick one of your warranties."})
        claim = services.raise_claim(warranty, request.user, request.data.get("issue"), self._ticket(request.data.get("repair_code"), warranty.party_id))
        return Response(self.get_serializer(claim).data, status=201)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        claim = services.decide_claim(self.get_object(), request.user, request.data.get("decision"), request.data.get("note"))
        return Response(self.get_serializer(claim).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        claim = self.get_object()
        ticket = self._ticket(request.data.get("repair_code"), claim.warranty.party_id)
        claim = services.resolve_claim(claim, request.user, request.data.get("resolution"), request.data.get("cost"), request.data.get("note"), ticket)
        return Response(self.get_serializer(claim).data)
