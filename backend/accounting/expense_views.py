"""
Accounting -> Expenses API. Every endpoint, attachment files included,
needs can_manage_expenses (403 and a PermissionDeniedLog row otherwise),
and every record is looked up through the account's StoreScope, so an
expense -- or an attachment -- at another store is a 404 whatever id is sent.

  GET    /expenses/                       list (filters, sorting, pages, totals)
  POST   /expenses/bulk/                  multipart: entries (JSON), attachments_<n>, submission_key
  GET    /expenses/<id>/                  details, payments, attachments, history
  PATCH  /expenses/<id>/                  correct details (accounting.expenses.update_expense)
  POST   /expenses/<id>/payments/         record a payment
  POST   /expenses/<id>/cancel/           cancel (reverses posted payments)
  POST   /expenses/<id>/attachments/      multipart: add files
  DELETE /expenses/<id>/attachments/<a>/  remove a file
  GET    /expense-attachments/<a>/file/   stream it (?download=1 to save)
  GET    /expense-categories/             categories
"""
import json
import re

from django.db.models import Count, Q, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import activity
from accounts.models import ActivityLog
from accounts.permissions import _log_denial
from accounts.store_scope import StoreScope

from . import expenses as svc
from .models import Expense, ExpenseAttachment, ExpenseCategory, ExpensePayment

FILE_FIELD_RE = re.compile(r"^attachments_(\d{1,3})$")


class CanManageExpenses(BasePermission):
    message = "Only a Superuser or an authorised Admin or Accounts user can manage expenses."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        allowed = svc.can_manage_expenses(request.user)
        if not allowed:
            _log_denial(request, svc.EXPENSES_PERM)
        return allowed


def _person(user):
    return (user.get_full_name() or user.username) if user else None


def scoped_expenses(user):
    return StoreScope(user).filter(Expense.objects.all(), "stock_point")


# --------------------------------------------------------------------------
# Serializers (read side; writes go through accounting.expenses)
# --------------------------------------------------------------------------

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "slug", "label", "classification", "is_active"]


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseAttachment
        fields = ["id", "original_name", "content_type", "kind", "size", "uploaded_at", "uploaded_by_name"]

    def get_uploaded_by_name(self, obj):
        return _person(obj.uploaded_by)

    def get_kind(self, obj):
        return "pdf" if obj.content_type == "application/pdf" else "image"


class PaymentSerializer(serializers.ModelSerializer):
    by_name = serializers.SerializerMethodField()
    book = serializers.SerializerMethodField()

    class Meta:
        model = ExpensePayment
        fields = ["id", "amount", "paid_on", "method", "reference", "by_name", "created_at", "reversed_at", "book"]

    def get_by_name(self, obj):
        return _person(obj.by)

    def get_book(self, obj):
        return "cash" if obj.method == "Cash" else "bank"


class ExpenseListSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    store = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="category.label", read_only=True)
    classification = serializers.CharField(source="category.classification", read_only=True)
    attachment_count = serializers.IntegerField(read_only=True)
    payment_method = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    recognised_amount = serializers.IntegerField(read_only=True)
    outstanding = serializers.IntegerField(read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "code", "expense_date", "store", "category", "category_label", "classification", "vendor", "reference",
            "amount", "gst_amount", "gst_claimable", "recognised_amount", "paid_amount", "outstanding", "payment_status",
            "payment_method", "status", "attachment_count", "created_by_name", "created_at",
        ]

    def get_store(self, obj):
        sp = obj.stock_point
        return {"id": sp.id, "name": sp.name, "kind": sp.kind} if sp else None

    def get_payment_method(self, obj):
        methods = sorted({p.method for p in obj.payments.all()})
        return ", ".join(methods) or None

    def get_created_by_name(self, obj):
        return _person(obj.created_by)


class ExpenseDetailSerializer(ExpenseListSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    updated_by_name = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta(ExpenseListSerializer.Meta):
        fields = ExpenseListSerializer.Meta.fields + [
            "description", "attachments", "payments", "updated_by_name", "updated_at",
            "cancelled_at", "cancel_reason", "cancelled_by_name", "history",
        ]

    def get_updated_by_name(self, obj):
        return _person(obj.updated_by)

    def get_cancelled_by_name(self, obj):
        return _person(obj.cancelled_by)

    def get_history(self, obj):
        # the Staff Activity Log rows about this expense (accounts.activity)
        rows = (ActivityLog.objects.filter(record_type="accounting.expense", record_id=str(obj.pk), outcome=ActivityLog.SUCCESS)
                .select_related("actor").order_by("-at", "-id")[:50])
        return [{"at": r.at, "by": _person(r.actor), "action": r.action, "description": r.description, "changes": r.changes} for r in rows]


def _detail(expense):
    expense = (Expense.objects.select_related("stock_point", "category", "created_by", "updated_by", "cancelled_by")
               .prefetch_related("payments__by", "attachments__uploaded_by")
               .annotate(attachment_count=Count("attachments", distinct=True)).get(pk=expense.pk))
    return ExpenseDetailSerializer(expense).data


def _error_response(e):
    return Response(e.errors, status=status.HTTP_400_BAD_REQUEST)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

class ExpenseCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [permissions.IsAuthenticated, CanManageExpenses]
    pagination_class = None


SORTS = {
    "date": ("expense_date", "id"), "-date": ("-expense_date", "-id"),
    "amount": ("amount", "id"), "-amount": ("-amount", "-id"),
    "id": ("id",), "-id": ("-id",),
}


class ExpenseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, CanManageExpenses]
    serializer_class = ExpenseListSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = (scoped_expenses(self.request.user).select_related("stock_point", "category", "created_by")
              .prefetch_related("payments").annotate(attachment_count=Count("attachments", distinct=True)))
        if self.action != "list":
            return qs
        p = self.request.query_params
        store = p.get("store")
        if store == "shared":
            qs = qs.filter(stock_point__isnull=True)
        elif store:
            try:
                qs = qs.filter(stock_point_id=int(store))
            except ValueError:
                raise ValidationError({"store": "Choose a store."})
        if p.get("category"):
            qs = qs.filter(category_id=p["category"]) if p["category"].isdigit() else qs.none()
        if p.get("payment_status") in dict(Expense.PAYMENT_STATUS_CHOICES):
            qs = qs.filter(payment_status=p["payment_status"])
        state = p.get("state") or "active"
        if state in dict(Expense.STATUS_CHOICES):
            qs = qs.filter(status=state)
        for name, lookup in (("date_from", "expense_date__gte"), ("date_to", "expense_date__lte")):
            if p.get(name):
                try:
                    qs = qs.filter(**{lookup: serializers.DateField().to_internal_value(p[name])})
                except serializers.ValidationError:
                    raise ValidationError({name: "Enter a date as YYYY-MM-DD."})
        if p.get("vendor"):
            qs = qs.filter(vendor__icontains=p["vendor"].strip())
        q = (p.get("q") or "").strip()
        if q:
            match = re.fullmatch(r"(?i)(?:exp-?)?0*(\d+)", q)
            qs = qs.filter(Q(reference__icontains=q) | (Q(pk=int(match.group(1))) if match else Q()))
        return qs.order_by(*SORTS.get(p.get("sort") or "-date", SORTS["-date"]))

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        totals = qs.order_by().aggregate(amount=Sum("amount"), paid=Sum("paid_amount"), count=Count("id"))
        page = self.paginate_queryset(qs)
        response = self.get_paginated_response(ExpenseListSerializer(page, many=True).data)
        response.data["totals"] = {
            "count": totals["count"], "amount": totals["amount"] or 0,
            "paid": totals["paid"] or 0, "outstanding": (totals["amount"] or 0) - (totals["paid"] or 0),
            # where the money went, for the same filters (largest first)
            "by_category": [
                {"id": r["category_id"], "label": r["category__label"], "amount": r["amount"] or 0, "count": r["count"]}
                for r in qs.order_by().values("category_id", "category__label")
                .annotate(amount=Sum("amount"), count=Count("id")).order_by("-amount")
            ],
        }
        return response

    def retrieve(self, request, *args, **kwargs):
        return Response(_detail(self.get_object()))

    def partial_update(self, request, *args, **kwargs):
        expense = self.get_object()
        try:
            expense = svc.update_expense(expense, request.user, request.data)
        except svc.ExpenseError as e:
            return _error_response(e)
        return Response(_detail(expense))

    @action(detail=False, methods=["get"])
    def meta(self, request):
        """What the expense form needs: categories, methods, limits, and
        whether this account may record shared / head-office expenses."""
        return Response({
            "categories": ExpenseCategorySerializer(ExpenseCategory.objects.all(), many=True).data,
            "payment_methods": svc.PAYMENT_METHODS,
            "payment_statuses": [{"id": k, "label": v} for k, v in Expense.PAYMENT_STATUS_CHOICES],
            "can_record_shared": StoreScope(request.user).all,
            "limits": {
                "max_entries": svc.MAX_ENTRIES, "max_file_bytes": svc.MAX_FILE_BYTES,
                "max_files_per_expense": svc.MAX_FILES_PER_EXPENSE, "max_files_per_submission": svc.MAX_FILES_PER_SUBMISSION,
                "extensions": sorted({e for exts in svc.ALLOWED_EXTENSIONS.values() for e in exts}),
            },
        })

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def bulk(self, request):
        try:
            entries = request.data.get("entries")
            entries = json.loads(entries) if isinstance(entries, str) else entries
        except ValueError:
            return Response({"entries": ["The expenses couldn't be read. Reload the form and try again."]}, status=400)
        files_by_entry = {}
        for field in request.FILES:
            match = FILE_FIELD_RE.match(field)
            if not match:
                return Response({"attachments": ["Unexpected file field. Reload the form and try again."]}, status=400)
            files_by_entry[int(match.group(1))] = request.FILES.getlist(field)
        try:
            result = svc.create_bulk(request.user, request.data.get("submission_key"), entries, files_by_entry)
        except svc.BulkValidationError as e:
            return Response({
                "detail": f"{len(e.problems)} of {len(entries)} {'entry needs' if len(e.problems) == 1 else 'entries need'} attention. Nothing was saved.",
                "entries": [{"entry": n, "errors": errs} for n, errs in sorted(e.problems.items())],
            }, status=400)
        except svc.ExpenseError as e:
            return _error_response(e)
        ids = [x.pk for x in result.expenses]
        rows = self.get_queryset().filter(pk__in=ids).order_by("id")
        return Response({
            "duplicate": result.duplicate,
            "count": len(ids),
            "total": sum(x.amount for x in result.expenses),
            "expenses": ExpenseListSerializer(rows, many=True).data,
        }, status=200 if result.duplicate else 201)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        expense = self.get_object()
        field = serializers.DateField(allow_null=True)
        try:
            amount = int(request.data.get("amount") or 0)
            paid_on = field.to_internal_value(request.data["payment_date"]) if request.data.get("payment_date") else None
        except (TypeError, ValueError, serializers.ValidationError):
            return Response({"detail": ["Enter a whole-rupee amount and a date."]}, status=400)
        try:
            svc.record_payment(expense, request.user, amount=amount, paid_on=paid_on,
                               method=request.data.get("payment_method") or "", reference=request.data.get("reference") or "")
        except svc.ExpenseError as e:
            return _error_response(e)
        return Response(_detail(expense), status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        expense = self.get_object()
        try:
            expense = svc.cancel_expense(expense, request.user, request.data.get("reason"))
        except svc.ExpenseError as e:
            return _error_response(e)
        return Response(_detail(expense))

    @action(detail=True, methods=["post"], url_path="attachments", parser_classes=[MultiPartParser, FormParser])
    def add_attachments(self, request, pk=None):
        expense = self.get_object()
        try:
            created = svc.add_attachments(expense, request.user, request.FILES.getlist("attachments"))
        except svc.ExpenseError as e:
            return _error_response(e)
        activity.note(expense, "attachments", f"Added {len(created)} attachment(s) to {expense.code}",
                      changes={"attachments": [None, ", ".join(a.original_name for a in created)]})
        return Response(_detail(expense), status=201)

    @action(detail=True, methods=["delete"], url_path=r"attachments/(?P<attachment_id>\d+)")
    def remove_attachment(self, request, pk=None, attachment_id=None):
        expense = self.get_object()
        attachment = get_object_or_404(ExpenseAttachment, pk=attachment_id, expense=expense)
        name = attachment.original_name
        try:
            svc.remove_attachment(attachment, request.user)
        except svc.ExpenseError as e:
            return _error_response(e)
        activity.note(expense, "attachment-removed", f"Removed attachment {name} from {expense.code}",
                      changes={"attachments": [name, None]})
        return Response(_detail(expense))


class ExpenseAttachmentFileView(APIView):
    """Streams one attachment to an account allowed to see its expense."""
    permission_classes = [permissions.IsAuthenticated, CanManageExpenses]

    def get(self, request, pk):
        attachment = get_object_or_404(ExpenseAttachment, pk=pk, expense__in=scoped_expenses(request.user))
        response = FileResponse(attachment.file.open("rb"), content_type=attachment.content_type)
        download = request.query_params.get("download") in ("1", "true")
        response["Content-Disposition"] = _disposition("attachment" if download else "inline", attachment.original_name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        return response


def _disposition(kind, name):
    from urllib.parse import quote

    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"

