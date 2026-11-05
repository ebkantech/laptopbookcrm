"""
Store-wise Profit & Loss (Store Locator -> a store -> Profit & Loss).

Nothing here is a second set of books: every figure is read from the same
records, by the same rules, as the existing Financial / Sales summary
reports (reports.views), so the totals reconcile with them.

Formulas (all amounts are whole rupees, as stored -- integer arithmetic,
no floats; percentages are Decimals rounded half-up to 0.1):

  Billed           = sum(qty x price) of the lines of SETTLED invoices
                     (Paid / Refunded) dated in the period, at the store.
                     Line prices are the invoiced (post-discount) prices;
                     a repair bill's "Less: advance received" line is
                     negative, so an advance and its final bill are never
                     counted twice.
  Refunds          = Refund.amount on those same invoices.
  Revenue          = Billed - Refunds  (== sum(Invoice.net_total), the
                     existing revenue rule). Refunds count against the
                     invoice's own date, exactly as the existing reports.
  COGS             = sum(qty x InvoiceItem.unit_cost) of the goods lines
                     (products and spare parts) on settled invoices of any
                     kind, less the cost of units returned AND put back on
                     the shelf (Refund.restocked). Units returned without
                     restocking stay in COGS -- the goods weren't recovered.
                     unit_cost is the cost locked on the line when it was
                     billed (the product's weighted average purchase cost,
                     the part's cost, or "our cost" typed on a repair line),
                     so correcting a cost later never rewrites past profit.
  Reliability      = "incomplete" when goods were billed with no cost at
                     all (they'd count as free) or sale lines aren't linked
                     to a product; else "estimated" when some costs are
                     still the automatic 78%-of-price guess; else
                     "complete". Labour, visit charges and rent carry no
                     goods cost by nature -- staff wages and rent paid are
                     expenses.
  Gross profit     = Revenue - COGS
  Operating / other expenses
                   = active (not cancelled) accounting.Expense rows at the
                     store with expense_date in the period, by their
                     category's classification, each at its amount less any
                     claimable input GST. Recognised on the expense date
                     whether or not it's paid; expense payments (and their
                     cash / bank entries) are never added again. Shared /
                     head-office expenses (no store) are never put on a
                     store -- they appear only in the all-store total.
  Net profit       = Gross profit - operating - other expenses, ONLY when
                     expense records exist for the period. With none (or
                     before the expense tables are migrated) expenses and net
                     profit are reported as unavailable (None), never as 0:
                     "nothing recorded" is not the same as "cost nothing".
  Tax: invoices carry no tax component, so any GST collected stays in
                     revenue (flagged in data_quality).

Left out on purpose: unpaid (Payment link sent / Overdue) invoices -- shown
only as receivables; cancelled invoices; customer payments, cash/bank book
entries and payment links (they mirror invoices already counted).
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection
from django.db.models import Case, Count, Exists, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

from accounts.permissions import _log_denial
from accounts.staff import is_staff_admin
from accounting.models import Expense
from sales.models import Invoice, InvoiceItem, Refund, RefundItem

PROFIT_LOSS_PERM = "reports.profit_loss"
SOURCES = (Invoice.SALE, Invoice.REPAIR, Invoice.RENTAL, Invoice.ONSITE)
PERIODS = ("today", "yesterday", "this_week", "this_month", "last_month", "this_year", "custom")
DEFAULT_PERIOD = "this_month"
MAX_CUSTOM_DAYS = 366 * 5
DAILY_TREND_MAX_DAYS = 62
MONTHLY_MIN, MONTHLY_MAX = 6, 24

LINE_VALUE = ExpressionWrapper(F("qty") * F("price"), output_field=IntegerField())
LINE_COST = ExpressionWrapper(F("qty") * F("unit_cost"), output_field=IntegerField())
RETURN_COST = ExpressionWrapper(F("qty") * F("invoice_item__unit_cost"), output_field=IntegerField())
# goods lines -- products and spare parts -- whose cost must be known
GOODS = Q(item_kind__in=(InvoiceItem.PRODUCT, InvoiceItem.PART))
COSTED = GOODS & Q(unit_cost__gt=0)
MISSING = GOODS & (Q(unit_cost__isnull=True) | Q(unit_cost=0))
ESTIMATED = COSTED & Q(cost_estimated=True)
RETURN_COSTED = Q(invoice_item__item_kind__in=(InvoiceItem.PRODUCT, InvoiceItem.PART), invoice_item__unit_cost__gt=0)
COSTED_SOURCES = (Invoice.SALE, Invoice.REPAIR, Invoice.ONSITE)  # sources that can bill goods
RELIABLE, ESTIMATED_COSTS, INCOMPLETE = "complete", "estimated", "incomplete"
# an expense as Profit & Loss counts it: the bill less claimable input GST
EXPENSE_VALUE = ExpressionWrapper(
    F("amount") - Case(When(gst_claimable=True, then=F("gst_amount")), default=Value(0)), output_field=IntegerField(),
)


# --------------------------------------------------------------------------
# Who may see it
# --------------------------------------------------------------------------

def can_view_profit_loss(user):
    """Superuser, or an Admin (accounts.staff.is_staff_admin: the Owner role
    or roles.manage) whose role ALSO holds reports.profit_loss. Holding the
    permission without being an Admin is not enough; is_staff plays no part.
    Which stores is a separate question -- accounts.store_scope.StoreScope."""
    if not user or not user.is_authenticated or hasattr(user, "customer_profile"):
        return False
    if user.is_superuser:
        return True
    return is_staff_admin(user) and user.has_perm_code(PROFIT_LOSS_PERM)


class CanViewProfitLoss(BasePermission):
    message = "Only a Superuser or an authorised Admin can view Profit & Loss."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        allowed = can_view_profit_loss(request.user)
        if not allowed:
            _log_denial(request, PROFIT_LOSS_PERM)
        return allowed


# --------------------------------------------------------------------------
# Reporting period (inclusive dates, in the configured TIME_ZONE)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    key: str
    start: date
    end: date

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def as_dict(self):
        return {"key": self.key, "start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def _parse_day(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError({field: "Enter a date as YYYY-MM-DD."})


def resolve_period(params, today=None):
    today = today or timezone.localdate()
    key = params.get("period") or DEFAULT_PERIOD
    if key not in PERIODS:
        raise ValidationError({"period": f"Choose one of: {', '.join(PERIODS)}."})
    if key == "today":
        return Period(key, today, today)
    if key == "yesterday":
        day = today - timedelta(days=1)
        return Period(key, day, day)
    if key == "this_week":  # Monday to today
        return Period(key, today - timedelta(days=today.weekday()), today)
    if key == "this_month":
        return Period(key, today.replace(day=1), today)
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return Period(key, end.replace(day=1), end)
    if key == "this_year":
        return Period(key, today.replace(month=1, day=1), today)
    start = _parse_day(params.get("date_from"), "date_from")
    end = _parse_day(params.get("date_to"), "date_to")
    if start > end:
        raise ValidationError({"date_to": "The end date can't be before the start date."})
    if (end - start).days + 1 > MAX_CUSTOM_DAYS:
        raise ValidationError({"date_to": "Choose a range of five years or less."})
    return Period(key, start, end)


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def _settled(prefix, store_ids, start, end):
    """Filter kwargs for rows reached through `prefix` (an Invoice path)."""
    p = f"{prefix}__" if prefix else ""
    # a security deposit is the customer's money, not income
    return {f"{p}stock_point_id__in": list(store_ids), f"{p}date__range": (start, end), f"{p}status__in": Invoice.SETTLED,
            f"{p}is_deposit": False}


def _empty_store():
    return {
        "billed": {s: 0 for s in SOURCES}, "refunds": {s: 0 for s in SOURCES}, "invoices": {s: 0 for s in SOURCES},
        "refund_count": 0, "cost": {s: 0 for s in SOURCES}, "restocked_cost": {s: 0 for s in SOURCES},
        "costed_lines": {s: 0 for s in SOURCES},
        "estimated_cost_lines": 0, "estimated_cost": 0, "estimated_value": 0,
        "missing_cost_lines": 0, "missing_cost_value": 0, "unlinked_sale_value": 0, "service_value": 0,
        "outstanding": 0, "outstanding_count": 0, "cancelled": 0, "cancelled_count": 0,
        "operating_expenses": 0, "other_expenses": 0, "expense_count": 0,
    }


def raw_figures(store_ids, start, end):
    """One aggregate query per figure, grouped by store -- the cost of a call
    doesn't grow with the number of invoices or stores."""
    store_ids = list(store_ids)
    out = {sid: _empty_store() for sid in store_ids}
    if not store_ids:
        return out

    for row in (InvoiceItem.objects.filter(**_settled("invoice", store_ids, start, end))
                .values("invoice__stock_point_id", "invoice__source").order_by().annotate(v=Sum(LINE_VALUE))):
        out[row["invoice__stock_point_id"]]["billed"][row["invoice__source"]] += row["v"] or 0

    for row in (Invoice.objects.filter(**_settled("", store_ids, start, end))
                .values("stock_point_id", "source").order_by().annotate(n=Count("id"))):
        out[row["stock_point_id"]]["invoices"][row["source"]] += row["n"]

    for row in (Refund.objects.filter(**_settled("invoice", store_ids, start, end))
                .values("invoice__stock_point_id", "invoice__source").order_by().annotate(v=Sum("amount"), n=Count("id"))):
        fig = out[row["invoice__stock_point_id"]]
        fig["refunds"][row["invoice__source"]] += row["v"] or 0
        fig["refund_count"] += row["n"]

    discount = Q(item_kind=InvoiceItem.DISCOUNT)
    unlinked = Q(invoice__source=Invoice.SALE) & ~GOODS & ~discount
    lines = InvoiceItem.objects.filter(**_settled("invoice", store_ids, start, end))
    for row in (lines.values("invoice__stock_point_id", "invoice__source").order_by().annotate(
            cost=Sum(LINE_COST, filter=COSTED),
            costed=Count("id", filter=COSTED),
            est_lines=Count("id", filter=ESTIMATED),
            est_cost=Sum(LINE_COST, filter=ESTIMATED),
            est_value=Sum(LINE_VALUE, filter=ESTIMATED),
            missing_lines=Count("id", filter=MISSING),
            missing_value=Sum(LINE_VALUE, filter=MISSING),
            unlinked=Sum(LINE_VALUE, filter=unlinked),
            service=Sum(LINE_VALUE, filter=~GOODS & ~unlinked & ~discount))):
        fig, src = out[row["invoice__stock_point_id"]], row["invoice__source"]
        fig["cost"][src] += row["cost"] or 0
        fig["costed_lines"][src] += row["costed"]
        fig["estimated_cost_lines"] += row["est_lines"]
        fig["estimated_cost"] += row["est_cost"] or 0
        fig["estimated_value"] += row["est_value"] or 0
        fig["missing_cost_lines"] += row["missing_lines"]
        fig["missing_cost_value"] += row["missing_value"] or 0
        fig["unlinked_sale_value"] += row["unlinked"] or 0
        fig["service_value"] += row["service"] or 0

    for row in (RefundItem.objects.filter(RETURN_COSTED, **_settled("refund__invoice", store_ids, start, end), refund__restocked=True)
                .values("refund__invoice__stock_point_id", "refund__invoice__source").order_by().annotate(cost=Sum(RETURN_COST))):
        out[row["refund__invoice__stock_point_id"]]["restocked_cost"][row["refund__invoice__source"]] += row["cost"] or 0

    open_or_cancelled = InvoiceItem.objects.filter(invoice__is_deposit=False, invoice__stock_point_id__in=store_ids, invoice__date__range=(start, end))
    for row in (open_or_cancelled.filter(invoice__status__in=Invoice.OUTSTANDING + (Invoice.CANCELLED,))
                .values("invoice__stock_point_id").order_by().annotate(
                    outstanding=Sum(LINE_VALUE, filter=Q(invoice__status__in=Invoice.OUTSTANDING)),
                    cancelled=Sum(LINE_VALUE, filter=Q(invoice__status=Invoice.CANCELLED)))):
        fig = out[row["invoice__stock_point_id"]]
        fig["outstanding"] = row["outstanding"] or 0
        fig["cancelled"] = row["cancelled"] or 0
    for row in (Invoice.objects.filter(stock_point_id__in=store_ids, date__range=(start, end))
                .values("stock_point_id").order_by().annotate(
                    open=Count("id", filter=Q(status__in=Invoice.OUTSTANDING)),
                    cancelled=Count("id", filter=Q(status=Invoice.CANCELLED)))):
        out[row["stock_point_id"]]["outstanding_count"] = row["open"]
        out[row["stock_point_id"]]["cancelled_count"] = row["cancelled"]

    if expenses_available():
        for row in expense_rows(Expense.objects.filter(stock_point_id__in=store_ids), start, end).values("stock_point_id", "category__classification").annotate(v=Sum(EXPENSE_VALUE), n=Count("id")):
            _add_expense(out[row["stock_point_id"]], row)
    return out


# expense_status values
EXPENSES_UNAVAILABLE, EXPENSES_NONE, EXPENSES_RECORDED = "unavailable", "none_recorded", "recorded"
_expense_table_seen = False


def expenses_available():
    """Whether the expense tables exist in this database (accounting
    migration 0005). Until they do, every expense figure is unavailable
    rather than an error or a zero."""
    global _expense_table_seen
    if not _expense_table_seen:
        with connection.cursor() as cursor:
            _expense_table_seen = Expense._meta.db_table in connection.introspection.table_names(cursor)
    return _expense_table_seen


def expense_rows(qs, start, end):
    return qs.filter(status=Expense.ACTIVE, expense_date__range=(start, end)).order_by()


def _add_expense(fig, row):
    key = "other_expenses" if row["category__classification"] == "other" else "operating_expenses"
    fig[key] += row["v"] or 0
    fig["expense_count"] += row["n"]


def shared_figures(start, end):
    """Shared / head-office expenses (no store) in the period."""
    fig = _empty_store()
    if not expenses_available():
        return fig
    for row in expense_rows(Expense.objects.filter(stock_point__isnull=True), start, end).values("category__classification").annotate(v=Sum(EXPENSE_VALUE), n=Count("id")):
        _add_expense(fig, row)
    return fig


def pct(part, whole):
    """part / whole as a percentage string ("23.4"), or None when whole is 0."""
    if not whole:
        return None
    value = (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(value)


def expense_status(fig):
    if not expenses_available():
        return EXPENSES_UNAVAILABLE
    return EXPENSES_RECORDED if fig["expense_count"] else EXPENSES_NONE


def statement(fig):
    """The Profit & Loss statement for one store's (or a total's) raw figures."""
    billed = sum(fig["billed"].values())
    refunds = sum(fig["refunds"].values())
    revenue = billed - refunds
    by_source = {s: fig["billed"][s] - fig["refunds"][s] for s in SOURCES}
    cogs_by = {s: fig["cost"][s] - fig["restocked_cost"][s] for s in SOURCES}
    # a source shows a cost only where goods can be billed and (beyond plain sales) some were
    shows_cost = {s: s == Invoice.SALE or (s in COSTED_SOURCES and fig["costed_lines"][s] > 0) for s in SOURCES}
    cogs = sum(cogs_by.values())
    gross = revenue - cogs
    # revenue with no goods cost: labour, visit charges, rent -- plus sale lines not linked to a product
    uncosted = fig["service_value"] + fig["unlinked_sale_value"]
    if fig["missing_cost_lines"] or fig["unlinked_sale_value"]:
        reliability = INCOMPLETE
    elif fig["estimated_cost_lines"]:
        reliability = ESTIMATED_COSTS
    else:
        reliability = RELIABLE
    status = expense_status(fig)
    known = status == EXPENSES_RECORDED
    net = gross - fig["operating_expenses"] - fig["other_expenses"] if known else None
    return {
        "billed": billed,
        "refunds": refunds,
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross,
        "gross_margin_pct": pct(gross, revenue),
        "operating_expenses": fig["operating_expenses"] if known else None,
        "other_expenses": fig["other_expenses"] if known else None,
        "expenses": fig["operating_expenses"] + fig["other_expenses"] if known else None,
        "expense_count": fig["expense_count"] if status != EXPENSES_UNAVAILABLE else None,
        "net_profit": net,
        "net_margin_pct": pct(net, revenue) if known else None,
        "transactions": sum(fig["invoices"].values()),
        "refund_count": fig["refund_count"],
        "receivables": {"amount": fig["outstanding"], "count": fig["outstanding_count"]},
        "cancelled": {"amount": fig["cancelled"], "count": fig["cancelled_count"]},
        "by_source": [
            {
                "source": s, "billed": fig["billed"][s], "refunds": fig["refunds"][s], "revenue": by_source[s],
                "invoices": fig["invoices"][s],
                "cogs": cogs_by[s] if shows_cost[s] else None,
                "gross_profit": by_source[s] - cogs_by[s] if shows_cost[s] else None,
                "gross_margin_pct": pct(by_source[s] - cogs_by[s], by_source[s]) if shows_cost[s] else None,
            }
            for s in SOURCES
        ],
        "data_quality": {
            "reliability": reliability,
            "cogs_complete": reliability == RELIABLE,
            "uncosted_revenue": uncosted,
            "service_revenue": fig["service_value"],
            "unlinked_sale_value": fig["unlinked_sale_value"],
            "missing_cost_lines": fig["missing_cost_lines"],
            "missing_cost_value": fig["missing_cost_value"],
            "estimated_cost_lines": fig["estimated_cost_lines"],
            "estimated_cost": fig["estimated_cost"],
            "estimated_value": fig["estimated_value"],
            "expense_status": status,
            "expenses_tracked": status != EXPENSES_UNAVAILABLE,
            "expenses_recorded": known,
            "tax_tracked": False,
            "cost_basis": "locked_at_sale",
        },
    }


def combine(figs):
    total = _empty_store()
    for fig in figs:
        for key, value in fig.items():
            if isinstance(value, dict):
                for s, v in value.items():
                    total[key][s] += v
            else:
                total[key] += value
    return total


# --------------------------------------------------------------------------
# Over time
# --------------------------------------------------------------------------

def _bucket_expr(path, monthly):
    return TruncMonth(path) if monthly else F(path)


def _as_day(value):
    return value.date() if hasattr(value, "date") and callable(value.date) else value


def bucketed(store_id, start, end, monthly):
    """{bucket date: {"revenue", "cogs"}} for one store, bucket = day or 1st of month."""
    rows = {}

    def add(qs, path, value, figure, sign=1):
        for row in qs.annotate(b=_bucket_expr(path, monthly)).values("b").order_by().annotate(v=Sum(value)):
            slot = rows.setdefault(_as_day(row["b"]), {"revenue": 0, "cogs": 0, "expenses": 0, "expense_n": 0})
            slot[figure] += sign * (row["v"] or 0)

    ids = [store_id]
    add(InvoiceItem.objects.filter(**_settled("invoice", ids, start, end)), "invoice__date", LINE_VALUE, "revenue")
    add(Refund.objects.filter(**_settled("invoice", ids, start, end)), "invoice__date", F("amount"), "revenue", -1)
    add(InvoiceItem.objects.filter(COSTED, **_settled("invoice", ids, start, end)), "invoice__date", LINE_COST, "cogs")
    add(RefundItem.objects.filter(RETURN_COSTED, **_settled("refund__invoice", ids, start, end), refund__restocked=True),
        "refund__invoice__date", RETURN_COST, "cogs", -1)
    if expenses_available():
        expenses = expense_rows(Expense.objects.filter(stock_point_id=store_id), start, end)
        add(expenses, "expense_date", EXPENSE_VALUE, "expenses")
        add(expenses, "expense_date", Value(1), "expense_n")
    return rows


def _month_starts(start, end):
    months, cur = [], start.replace(day=1)
    while cur <= end:
        months.append(cur)
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def _point(bucket, slot, known):
    """`known`: expense records exist for the span this point belongs to --
    otherwise its expenses and net profit are unavailable (None)."""
    revenue, cogs = slot["revenue"], slot["cogs"]
    expenses = slot.get("expenses", 0) if known else None
    return {"bucket": bucket.isoformat(), "revenue": revenue, "cogs": cogs, "expenses": expenses,
            "gross_profit": revenue - cogs, "net_profit": revenue - cogs - expenses if known else None}


def trend(store_id, period):
    """Revenue / COGS / gross profit across the period: daily up to
    DAILY_TREND_MAX_DAYS, monthly beyond. Empty buckets are zeros."""
    monthly = period.days > DAILY_TREND_MAX_DAYS
    rows = bucketed(store_id, period.start, period.end, monthly)
    empty = {"revenue": 0, "cogs": 0, "expenses": 0}
    if monthly:
        buckets = _month_starts(period.start, period.end)
    else:
        buckets = [period.start + timedelta(days=i) for i in range(period.days)]
    # net per day / month only when the period has expense records at all
    known = any(slot.get("expense_n") for slot in rows.values())
    return {"granularity": "month" if monthly else "day", "points": [_point(b, rows.get(b, empty), known) for b in buckets]}


def monthly_comparison(store_id, period):
    """Whole calendar months ending with the period's last month: the months
    the period spans, at least MONTHLY_MIN (earlier months added for
    context) and at most MONTHLY_MAX."""
    months = _month_starts(period.start, period.end)
    while len(months) < MONTHLY_MIN:
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    months = months[-MONTHLY_MAX:]
    last = months[-1]
    month_end = (last.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rows = bucketed(store_id, months[0], month_end, monthly=True)
    empty = {"revenue": 0, "cogs": 0, "expenses": 0}
    # each month on its own: a month with no expense records has no net profit
    return [_point(m, rows.get(m, empty), bool(rows.get(m, empty).get("expense_n"))) for m in months]


# --------------------------------------------------------------------------
# Underlying transactions
# --------------------------------------------------------------------------

TRANSACTION_KINDS = ("settled", "refunds", "receivables", "cancelled", "expenses")


def invoice_rows(store_id, period, kind, source=None):
    statuses = {"settled": Invoice.SETTLED, "receivables": Invoice.OUTSTANDING, "cancelled": (Invoice.CANCELLED,)}[kind]
    billed = (InvoiceItem.objects.filter(invoice=OuterRef("pk")).order_by().values("invoice")
              .annotate(v=Sum(LINE_VALUE)).values("v"))
    refunded = Refund.objects.filter(invoice=OuterRef("pk")).order_by().values("invoice").annotate(v=Sum("amount")).values("v")
    cost = (InvoiceItem.objects.filter(COSTED, invoice=OuterRef("pk")).order_by().values("invoice")
            .annotate(v=Sum(LINE_COST)).values("v"))
    restocked = (RefundItem.objects.filter(RETURN_COSTED, refund__invoice=OuterRef("pk"), refund__restocked=True)
                 .order_by().values("refund__invoice").annotate(v=Sum(RETURN_COST)).values("v"))
    zero = Value(0, output_field=IntegerField())
    qs = (Invoice.objects.filter(stock_point_id=store_id, date__range=(period.start, period.end), status__in=statuses)
          .select_related("party")
          .annotate(
              billed_v=Coalesce(Subquery(billed, output_field=IntegerField()), zero),
              refunded_v=Coalesce(Subquery(refunded, output_field=IntegerField()), zero),
              cost_v=Case(
                  When(source=Invoice.SALE, then=Coalesce(Subquery(cost, output_field=IntegerField()), zero)
                       - Coalesce(Subquery(restocked, output_field=IntegerField()), zero)),
                  # repair / on-site: a cost only when parts with a cost were billed
                  When(source__in=(Invoice.REPAIR, Invoice.ONSITE), then=Subquery(cost, output_field=IntegerField())
                       - Coalesce(Subquery(restocked, output_field=IntegerField()), zero)),
                  default=None, output_field=IntegerField()),
              cost_estimated=Exists(InvoiceItem.objects.filter(ESTIMATED, invoice=OuterRef("pk"))),
              cost_missing=Exists(InvoiceItem.objects.filter(MISSING, invoice=OuterRef("pk"))),
          ).order_by("-date", "-id"))
    if source in SOURCES:
        qs = qs.filter(source=source)
    return qs


def serialize_invoice(inv, kind):
    counted = kind == "settled"
    revenue = inv.billed_v - inv.refunded_v
    return {
        "id": inv.id, "code": inv.code, "date": inv.date.isoformat(), "source": inv.source, "status": inv.status,
        "party": inv.party.name, "pay_method": inv.pay_method, "is_advance": inv.is_advance,
        "billed": inv.billed_v, "refunded": inv.refunded_v,
        "revenue": revenue if counted else 0,
        "cogs": inv.cost_v if counted else None,
        "gross_profit": (revenue - inv.cost_v) if counted and inv.cost_v is not None else None,
        "cost_estimated": inv.cost_estimated,
        "cost_missing": inv.cost_missing,
    }


def refund_rows(store_id, period, source=None):
    restocked_cost = (RefundItem.objects.filter(RETURN_COSTED, refund=OuterRef("pk")).order_by()
                      .values("refund").annotate(v=Sum(RETURN_COST)).values("v"))
    qs = (Refund.objects.filter(**_settled("invoice", [store_id], period.start, period.end))
          .select_related("invoice__party")
          .annotate(returned_cost=Coalesce(Subquery(restocked_cost, output_field=IntegerField()), Value(0)))
          .order_by("-invoice__date", "-id"))
    if source in SOURCES:
        qs = qs.filter(invoice__source=source)
    return qs


def serialize_refund(refund):
    return {
        "id": refund.id, "invoice_id": refund.invoice_id, "code": refund.invoice.code,
        "invoice_date": refund.invoice.date.isoformat(), "refunded_on": refund.refunded_on.isoformat(),
        "source": refund.invoice.source, "party": refund.invoice.party.name, "amount": refund.amount,
        "method": refund.method, "reason": refund.reason, "restocked": refund.restocked,
        "cogs_reversed": refund.returned_cost if refund.restocked else 0,
    }


def expense_list(store_id, period):
    return (expense_rows(Expense.objects.filter(stock_point_id=store_id), period.start, period.end)
            .select_related("category").annotate(counted=EXPENSE_VALUE).order_by("-expense_date", "-id"))


def serialize_expense(expense):
    return {
        "id": expense.id, "code": expense.code, "date": expense.expense_date.isoformat(), "category": expense.category.label,
        "classification": expense.category.classification, "vendor": expense.vendor, "reference": expense.reference,
        "amount": expense.amount, "gst_claimable": expense.gst_amount if expense.gst_claimable else 0,
        "counted": expense.counted, "payment_status": expense.payment_status,
    }
