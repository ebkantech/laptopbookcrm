from datetime import date

from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasPerm
from accounts.store_scope import StoreScopedMixin
from sales.models import PAYMENT_METHODS, Invoice
from sales.services import on_invoice_paid
from crmbook_backend.notify import notify_staff

from . import services
from .models import Lead
from .serializers import (
    LeadDetailSerializer, LeadListSerializer, LeadWriteSerializer, PublicApprovalSerializer, PublicDecisionSerializer, QuoteSerializer,
)


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class LeadViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    """On-site service jobs. Technicians see only the jobs assigned to them;
    anyone who can create, assign or manage jobs sees the whole store."""
    queryset = Lead.objects.select_related("party", "stock_point", "assigned_to").all()
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "leads.view", "retrieve": "leads.view", "create": "leads.create", "partial_update": "leads.manage",
        "technicians": "leads.view", "assign": None, "check_in": None, "diagnose": None, "quote": None, "send_link": None,
        "approve": "leads.approve", "start": None, "complete": None, "advance": None, "collect": None,
        "close_credit": "leads.manage", "cancel": None, "to_store": None, "reschedule": "leads.manage",
        "issue_parts": None, "return_parts": None, "write_off_parts": None, "parts_due": "leads.view",
    }

    def get_queryset(self):
        # Technicians are not tied to a store: they see exactly the jobs
        # assigned to them, wherever the job is. Everyone who creates, assigns
        # or manages jobs is limited to their store (the Owner / Super Admin
        # sees every store).
        qs = Lead.objects.select_related("party", "stock_point", "assigned_to").all()
        user = self.request.user
        scope = self.store_scope
        if scope.all:
            pass  # Owner / Super Admin: every job
        elif services.sees_all_jobs(user) and scope.store_id is not None:
            # store staff: their store's jobs, plus any job given to them personally
            qs = qs.filter(Q(stock_point_id=scope.store_id) | Q(assigned_to=user))
        else:
            qs = qs.filter(assigned_to=user)
        p = self.request.query_params
        if p.get("status") in dict(Lead.STATUS_CHOICES):
            qs = qs.filter(status=p["status"])
        elif p.get("group") == "open":
            qs = qs.filter(status__in=Lead.OPEN)
        elif p.get("group") == "finished":
            qs = qs.filter(status__in=Lead.FINISHED)
        if p.get("mine") == "1":
            qs = qs.filter(assigned_to=self.request.user)
        term = (p.get("q") or "").strip()
        if term:
            qs = qs.filter(Q(code__icontains=term) | Q(party__name__icontains=term) | Q(contact_phone__icontains=term)
                           | Q(site_address__icontains=term) | Q(device__icontains=term))
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return LeadListSerializer
        if self.action in ("create", "partial_update"):
            return LeadWriteSerializer
        return LeadDetailSerializer

    def _detail(self, lead):
        lead = self.get_queryset().prefetch_related("quotes__lines", "approvals", "events", "invoices__items", "part_issues__technician", "part_issues__lead").get(pk=lead.pk)
        return Response(LeadDetailSerializer(lead, context=self.get_serializer_context()).data)

    def retrieve(self, request, *args, **kwargs):
        return self._detail(self.get_object())

    def create(self, request, *args, **kwargs):
        self.store_scope.require_assigned()
        ser = LeadWriteSerializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        self.store_scope.require(ser.validated_data["stock_point"].id, "jobs")
        data = dict(ser.validated_data)
        lead = services.create_lead(request.user, **data)
        return self._detail(lead)

    def partial_update(self, request, *args, **kwargs):
        lead = self.get_object()
        if lead.status in Lead.FINISHED or lead.status in (Lead.WORK_DONE,):
            raise ValidationError({"detail": "This job can't be edited any more."})
        ser = LeadWriteSerializer(lead, data=request.data, partial=True, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        if "stock_point" in ser.validated_data and ser.validated_data["stock_point"].id != lead.stock_point_id:
            raise ValidationError({"stock_point": "A job can't be moved to another store."})
        changed = [f for f, v in ser.validated_data.items() if getattr(lead, f) != v and f != "assigned_to"]
        ser.save()
        services.log(lead, "edited", "Details updated: " + ", ".join(changed) if changed else "Details updated", request.user)
        return self._detail(lead)

    @action(detail=False, methods=["get"])
    def technicians(self, request):
        """Everyone who can be given on-site jobs. Technicians belong to no
        particular store, so any of them can be assigned to any job."""
        qs = User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(role__permissions__codename="leads.work")).distinct()
        if not request.user.has_perm_code("leads.outsource"):
            qs = qs.exclude(staff_kind=User.OUTSOURCED)  # only Admin / Super Admin can pick outsourced technicians
        return Response([{"id": u.id, "name": u.get_full_name() or u.username, "stock_point": u.stock_point_id,
                          "stock_point_name": "", "same_store": True, "kind": u.staff_kind, "company": u.company}
                         for u in qs.order_by("first_name", "username")])

    # -- workflow ---------------------------------------------------------
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        if not (request.user.has_perm_code("leads.assign") or request.user.has_perm_code("leads.manage")):
            raise PermissionDenied("You do not have permission to assign jobs.")
        lead = self.get_object()
        try:
            tech = User.objects.get(pk=request.data.get("assigned_to"), is_active=True)
        except (User.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"assigned_to": "Pick a technician."})
        if not tech.has_perm_code("leads.work"):
            raise ValidationError({"assigned_to": "That person can't be given on-site jobs."})
        if tech.staff_kind == User.OUTSOURCED and not request.user.has_perm_code("leads.outsource"):
            raise PermissionDenied("Only a Super Admin or Admin can give a job to an outsourced technician.")
        services.assign(lead, tech, request.user)
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        lead = self.get_object()
        when = parse_datetime(str(request.data.get("preferred_at") or ""))
        services.reschedule(lead, request.user, when, (request.data.get("reason") or "").strip()[:150])
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def check_in(self, request, pk=None):
        lead = self.get_object()
        lat, lng = request.data.get("lat"), request.data.get("lng")
        try:
            lat = round(float(lat), 6) if lat not in (None, "") else None
            lng = round(float(lng), 6) if lng not in (None, "") else None
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Location is not valid."})
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValidationError({"detail": "Location is not valid."})
        services.check_in(lead, request.user, lat, lng, (request.data.get("note") or "")[:150])
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def diagnose(self, request, pk=None):
        lead = self.get_object()
        services.diagnose(lead, request.user, request.data.get("diagnosis"))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def quote(self, request, pk=None):
        lead = self.get_object()
        services.save_quote(lead, request.user, request.data.get("lines"), request.data.get("note", ""))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def send_link(self, request, pk=None):
        lead = self.get_object()
        approval, url, wa_url, delivery = services.issue_approval_link(lead, request.user, send=bool(request.data.get("send_whatsapp")))
        return Response({"approval_url": url, "whatsapp_url": wa_url, "expires_at": approval.expires_at,
                         "delivery": (delivery or {}).get("status") if delivery else None, "lead": self._detail(lead).data})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        lead = self.get_object()
        services.approve_on_behalf(lead, request.user, request.data.get("reason"))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        lead = self.get_object()
        services.start_work(lead, request.user)
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        lead = self.get_object()
        services.complete_work(lead, request.user, request.data.get("notes", ""))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        lead = self.get_object()
        services.raise_advance(lead, request.user, request.data.get("amount"))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def collect(self, request, pk=None):
        """Record a payment for the job's bill (or, with "invoice", for one
        of its advance invoices) -- the same checks as Invoices -> Settle."""
        user = request.user
        if not (user.has_perm_code("leads.collect") or user.has_perm_code("leads.manage")):
            raise PermissionDenied("You do not have permission to collect payment.")
        lead = self.get_object()
        if request.data.get("invoice"):
            invoice = lead.invoices.filter(pk=request.data.get("invoice")).first()
        else:
            invoice = services.bill_invoice(lead)
        if not invoice:
            raise ValidationError({"detail": "There is no bill to collect on yet."})
        if invoice.status in Invoice.SETTLED:
            raise ValidationError({"detail": "This invoice is already paid."})
        if invoice.status == Invoice.CANCELLED:
            raise ValidationError({"detail": "This invoice was cancelled."})
        method = (request.data.get("pay_method") or "").strip()
        reference = (request.data.get("payment_reference") or "").strip()
        if method not in PAYMENT_METHODS:
            raise ValidationError({"pay_method": f"Choose one of: {', '.join(PAYMENT_METHODS)}."})
        if method != "Cash" and not reference:
            raise ValidationError({"payment_reference": "Enter the payment reference (UPI/UTR, cheque or card number)."})
        if len(reference) > 80:
            raise ValidationError({"payment_reference": "Keep the reference under 80 characters."})
        try:
            paid_on = date.fromisoformat(request.data["paid_on"]) if request.data.get("paid_on") else date.today()
        except (TypeError, ValueError):
            raise ValidationError({"paid_on": "Use a date like 2026-10-31."})
        if paid_on > date.today():
            raise ValidationError({"paid_on": "The payment date can't be in the future."})
        invoice.status, invoice.pay_method, invoice.payment_reference = Invoice.PAID, method, reference
        invoice.paid_on, invoice.settled_by = paid_on, user
        invoice.save(update_fields=["status", "pay_method", "payment_reference", "paid_on", "settled_by"])
        on_invoice_paid(invoice)
        notify_staff("payment_received", f"Invoice {invoice.code} settled",
                     f"Invoice {invoice.code} for {invoice.party.name} was marked paid -- ₹{invoice.total}.")
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def to_store(self, request, pk=None):
        lead = self.get_object()
        services.take_to_store(lead, request.user, request.data.get("reason"), request.data.get("charge_visit", True) not in (False, "false", "0", 0))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def issue_parts(self, request, pk=None):
        """Hand a part or product to this job's technician (stock leaves the shelf, no invoice)."""
        lead = self.get_object()
        services.issue_parts(lead, request.user, request.data.get("kind"), request.data.get("item"),
                             request.data.get("qty"), request.data.get("note", ""))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def return_parts(self, request, pk=None):
        """Take unused stock back from the technician onto the store's shelf."""
        lead = self.get_object()
        services.receive_return(lead, request.user, request.data.get("issue"), request.data.get("qty"))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def write_off_parts(self, request, pk=None):
        """Close out lost or damaged stock from the technician's account (Admin, with a reason)."""
        lead = self.get_object()
        services.write_off(lead, request.user, request.data.get("issue"), request.data.get("qty"), request.data.get("reason"))
        return self._detail(lead)

    @action(detail=False, methods=["get"])
    def parts_due(self, request):
        """Stock out with technicians. Everyone sees what they hold themselves;
        people who handle parts (Admin / Super Admin) also see their store's team."""
        from django.db.models import F
        from .models import LeadPartIssue
        from .serializers import PartIssueSerializer

        user = request.user
        qs = LeadPartIssue.objects.filter(qty_issued__gt=F("qty_used") + F("qty_returned") + F("qty_written_off")).select_related("lead", "technician")
        scope = self.store_scope
        if services.can_handle_parts(user):
            if not scope.all:
                qs = qs.filter(lead__stock_point_id=scope.store_id) if scope.store_id is not None else qs.filter(technician=user)
        else:
            qs = qs.filter(technician=user)
        rows = PartIssueSerializer(qs.order_by("issued_at"), many=True).data
        return Response({
            "items": rows,
            "due_now": sum(1 for r in rows if r["due_now"]),
            "holding": sum(1 for r in rows if not r["due_now"]),
            "mine_due_now": sum(1 for r in rows if r["due_now"] and r["technician"] == user.id),
            "can_manage": services.can_handle_parts(user),
        })

    @action(detail=True, methods=["post"])
    def close_credit(self, request, pk=None):
        lead = self.get_object()
        services.close_on_credit(lead, request.user, request.data.get("reason"))
        return self._detail(lead)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        lead = self.get_object()
        services.cancel(lead, request.user, request.data.get("reason"), bool(request.data.get("charge_visit")))
        return self._detail(lead)


class LeadApprovalPublicView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "lead_approval"

    @staticmethod
    def _private(data, code=status.HTTP_200_OK):
        response = Response(data, status=code)
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        response["Referrer-Policy"] = "no-referrer"
        return response

    def get(self, request, token):
        return self._private(PublicApprovalSerializer(services.get_public_approval(token)).data)

    def post(self, request, token):
        payload = PublicDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        approval = services.customer_decide(
            token, d["decision"], d.get("consent", False), d.get("reason", ""),
            ip_address=_client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
        return self._private(PublicApprovalSerializer(approval).data)
