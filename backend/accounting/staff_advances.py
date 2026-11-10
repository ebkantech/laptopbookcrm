"""
Advances to staff: money given ahead of salary, and how it's recovered.

  GET  /api/staff-advances/              every staff member with given / recovered / still owed
  GET  /api/staff-advances/<user id>/    one person's entries
  POST /api/staff-advances/<user id>/    {kind: given | returned | salary, amount, date, method, reference, note, stock_point}

Accounting (accounting.models.StaffAdvanceEntry):
  * given     -> cash book "out" for Cash, else the business bank account "out".
                 It's money owed back, so it is NOT an expense.
  * returned  -> cash / bank "in".
  * salary    -> a Salary expense for the amount kept back, already paid (the
                 cash left when the advance was given), so Profit & Loss shows
                 the full salary while the books post nothing new.
Recovered (returned + salary) can never be more than what was given.

Who: the people who manage expenses (accounting.expenses.can_manage_expenses),
limited to the stores they see.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.store_scope import StoreScope
from catalog.models import StockPoint
from sales.models import PAYMENT_METHODS

from .expenses import can_manage_expenses
from .models import BankEntry, CashEntry, Expense, ExpenseCategory, StaffAdvanceEntry
from .posting import default_bank_account

User = get_user_model()


class CanManageAdvances(permissions.BasePermission):
    message = "Your role can't manage staff advances."

    def has_permission(self, request, view):
        return can_manage_expenses(request.user)


def _name(user):
    return user.get_full_name() or user.username


def _staff_queryset(viewer):
    """Active staff accounts the viewer may see."""
    qs = (User.objects.filter(is_active=True, is_superuser=False)
          .select_related("role", "stock_point").order_by("first_name", "last_name", "username"))
    scope = StoreScope(viewer)
    if not scope.all:
        qs = qs.filter(Q(stock_point_id=scope.store_id) | Q(advance_entries__stock_point_id=scope.store_id)).distinct()
    return qs


def balances(staff_ids=None):
    """{user id: {"given", "returned", "salary"}}"""
    rows = StaffAdvanceEntry.objects.all()
    if staff_ids is not None:
        rows = rows.filter(staff_id__in=staff_ids)
    out = {}
    for r in rows.values("staff_id", "kind").annotate(total=Sum("amount")):
        out.setdefault(r["staff_id"], {"given": 0, "returned": 0, "salary": 0})[r["kind"]] = r["total"] or 0
    return out


def _summary(user, b, last):
    b = b or {"given": 0, "returned": 0, "salary": 0}
    recovered = b["returned"] + b["salary"]
    return {
        "id": user.id, "name": _name(user), "username": user.username,
        "role": user.role.label if user.role_id else ("Owner / Super Admin" if user.is_superuser else ""),
        "store": user.stock_point.name if user.stock_point_id else ("Field / any store" if user.is_store_free else ""),
        "phone": user.phone,
        "given": b["given"], "returned": b["returned"], "salary": b["salary"], "recovered": recovered,
        "outstanding": b["given"] - recovered, "last_entry": last,
    }


def _entry(e):
    return {
        "id": e.id, "kind": e.kind, "kind_label": e.get_kind_display(), "date": e.date, "amount": e.amount,
        "method": e.method, "reference": e.reference, "note": e.note,
        "store": e.stock_point.name if e.stock_point_id else "", "expense_code": e.expense.code if e.expense_id else "",
        "by": _name(e.by), "created_at": e.created_at,
    }


class EntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[k for k, _ in StaffAdvanceEntry.KIND_CHOICES])
    amount = serializers.IntegerField(min_value=1, max_value=10_000_000)
    date = serializers.DateField()
    method = serializers.ChoiceField(choices=PAYMENT_METHODS, required=False, allow_blank=True, default="")
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    stock_point = serializers.PrimaryKeyRelatedField(queryset=StockPoint.objects.all(), required=False, allow_null=True, default=None)

    def validate(self, attrs):
        staff, viewer = self.context["staff"], self.context["viewer"]
        errors = {}
        if attrs["date"] > timezone.localdate():
            errors["date"] = ["The date can't be in the future."]
        if attrs["kind"] != StaffAdvanceEntry.SALARY and not attrs["method"]:
            errors["method"] = ["Choose how the money was paid."]
        if attrs["kind"] == StaffAdvanceEntry.SALARY:
            attrs["method"] = ""
        if attrs["kind"] != StaffAdvanceEntry.GIVEN:
            b = balances([staff.id]).get(staff.id, {"given": 0, "returned": 0, "salary": 0})
            owed = b["given"] - b["returned"] - b["salary"]
            if owed <= 0:
                errors["amount"] = [f"{_name(staff)} has no advance to recover."]
            elif attrs["amount"] > owed:
                errors["amount"] = [f"{_name(staff)} owes only ₹{owed:,}."]
        store = attrs["stock_point"] or staff.stock_point
        scope = StoreScope(viewer)
        if store is not None and not scope.all and store.id != scope.store_id:
            errors["stock_point"] = ["You can only record advances for your own store."]
        attrs["stock_point"] = store
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def _post(entry):
    """given -> money out; returned -> money in. Cash to the cash book, anything else to the bank."""
    out = entry.kind == StaffAdvanceEntry.GIVEN
    who = _name(entry.staff)
    particulars = (f"Advance to {who}" if out else f"Advance paid back by {who}") + (f" -- {entry.note}" if entry.note else "")
    if entry.method == "Cash":
        return CashEntry.objects.create(date=entry.date, particulars=particulars[:160], type=CashEntry.OUT if out else CashEntry.IN,
                                        amount=entry.amount, by=entry.by, staff_advance=entry)
    return BankEntry.objects.create(account=default_bank_account(), date=entry.date, type=BankEntry.OUT if out else BankEntry.IN,
                                    amount=entry.amount, particulars=f"{particulars} via {entry.method}"[:160],
                                    reference=entry.reference[:80], staff_advance=entry)


def _salary_expense(entry):
    """The part of the salary kept back to clear the advance: a Salary expense, already settled."""
    category = ExpenseCategory.objects.filter(slug="salary").first()
    if category is None:
        raise serializers.ValidationError({"kind": ["Add a “Salary” expense category first (Django admin)."]})
    return Expense.objects.create(
        stock_point=entry.stock_point, category=category, expense_date=entry.date, amount=entry.amount,
        vendor=_name(entry.staff)[:120], reference="Advance adjusted",
        description=f"Salary of {_name(entry.staff)} kept back to clear their advance.{(' ' + entry.note) if entry.note else ''}",
        paid_amount=entry.amount, payment_status=Expense.PAID, created_by=entry.by, updated_by=entry.by,
    )


@transaction.atomic
def record(staff, data, viewer):
    User.objects.select_for_update().filter(pk=staff.pk).first()  # one entry at a time per person
    entry = StaffAdvanceEntry.objects.create(staff=staff, by=viewer, **data)
    if entry.kind == StaffAdvanceEntry.SALARY:
        entry.expense = _salary_expense(entry)
        entry.save(update_fields=["expense"])
    else:
        _post(entry)
    return entry


class StaffAdvanceListView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanManageAdvances]

    def get(self, request):
        staff = list(_staff_queryset(request.user))
        ids = [u.id for u in staff]
        b = balances(ids)
        last = {}
        for row in StaffAdvanceEntry.objects.filter(staff_id__in=ids).order_by("staff_id", "-date", "-id").values("staff_id", "date"):
            last.setdefault(row["staff_id"], row["date"])
        rows = [_summary(u, b.get(u.id), last.get(u.id)) for u in staff]
        rows.sort(key=lambda r: (-r["outstanding"], r["name"].lower()))
        return Response({
            "staff": rows,
            "totals": {k: sum(r[k] for r in rows) for k in ("given", "recovered", "outstanding")},
            "with_advance": sum(1 for r in rows if r["outstanding"] > 0),
            "methods": PAYMENT_METHODS,
        })


class StaffAdvanceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanManageAdvances]

    def _staff(self, request, pk):
        return get_object_or_404(_staff_queryset(request.user), pk=pk)

    def get(self, request, pk):
        staff = self._staff(request, pk)
        entries = StaffAdvanceEntry.objects.filter(staff=staff).select_related("by", "stock_point", "expense").order_by("-date", "-id")
        b = balances([staff.id]).get(staff.id)
        last = entries[0].date if entries else None
        return Response({"staff": _summary(staff, b, last), "entries": [_entry(e) for e in entries]})

    def post(self, request, pk):
        staff = self._staff(request, pk)
        payload = EntrySerializer(data=request.data, context={"staff": staff, "viewer": request.user})
        payload.is_valid(raise_exception=True)
        record(staff, payload.validated_data, request.user)
        return self.get(request, pk)
