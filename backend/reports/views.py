from collections import defaultdict
from datetime import date

from django.db.models import Count, Prefetch
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope
from catalog.models import StockPoint
from catalog.views import product_queryset
from parties.models import Party
from portal.models import Feedback, PortalAccessLog
from rentals.models import Rental, RentalAsset
from rentals.scope import rental_queryset_for
from repairs.models import RepairTicket
from sales.models import Invoice, InvoiceItem
from sales.services import mark_overdue
from . import profit_loss
from .utils import last_n_months, month_label

# Task 7: both reports below are gated the same way, matching the
# "Who sees it" column in the Phase 2 build doc exactly -- Financial
# summary and Sales summary are both listed as "Owner, Admin, Accounts",
# and reports.export is already held by exactly those roles (owner,
# manager/"Admin", accountant/"Accounts"), plus Auditor, whose whole
# role is read-only visibility across the business -- a reasonable
# inclusion the doc doesn't contradict. Sales Staff and Repair Staff
# don't hold reports.export, so they're correctly excluded here; later
# reports in this task (Rental portfolio, Repair turnaround) will need
# a different permission when built, since the doc lists Sales/Repair
# Staff as intended viewers of those two.
REPORT_MONTHS = 12

# Store scope: every report below is computed only from records the
# requesting account's store owns (accounts.store_scope) -- the Owner sees
# the whole business, store staff their own store, unassigned staff nothing.
# The feedback & portal report is the exception: Feedback and portal logs
# carry no store link at all, so there is nothing store-owned to filter.


class FinancialSummaryReportView(APIView):
    """
    Task 7: "Financial summary (revenue, outstanding, by month)" --
    sourced from sales.Invoice and rentals.Rental per the doc. Revenue and
    outstanding cover every invoice in the ledger: sales, repairs and rent.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "reports.export"

    def get(self, request):
        months = last_n_months(REPORT_MONTHS)
        range_start = date(months[0][0], months[0][1], 1)

        scope = StoreScope(request.user)
        invoices = scope.filter(Invoice.objects.filter(is_deposit=False), "stock_point")
        revenue_by_month = {ym: 0 for ym in months}
        for inv in invoices.filter(status__in=Invoice.SETTLED, date__gte=range_start).prefetch_related("items", "refunds"):
            key = (inv.date.year, inv.date.month)
            if key in revenue_by_month:
                revenue_by_month[key] += inv.net_total

        mark_overdue()
        outstanding_invoices = invoices.filter(status__in=Invoice.OUTSTANDING)
        outstanding_total = sum(inv.total for inv in outstanding_invoices)

        rentals = rental_queryset_for(scope, Rental.objects.all())
        active_rentals = rentals.filter(status__in=[Rental.APPROVED, Rental.ACTIVE])

        return Response({
            "monthly_revenue": [
                {"month": month_label(y, m), "revenue": revenue_by_month[(y, m)]}
                for (y, m) in months
            ],
            "outstanding_total": outstanding_total,
            "outstanding_count": outstanding_invoices.count(),
            "rentals_active_monthly_value": sum(r.monthly_fee for r in active_rentals),
            "rentals_active_count": active_rentals.count(),
            "rentals_pending_approval": rentals.filter(status=Rental.PENDING_APPROVAL).count(),
        })


class SalesSummaryReportView(APIView):
    """
    Task 7: "Sales summary (by period, by stock point)" -- sourced
    from sales.Invoice per the doc.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "reports.export"

    def get(self, request):
        months = last_n_months(REPORT_MONTHS)
        range_start = date(months[0][0], months[0][1], 1)

        scope = StoreScope(request.user)
        all_invoices = list(
            scope.filter(Invoice.objects.filter(source=Invoice.SALE, date__gte=range_start), "stock_point")
            .exclude(status=Invoice.CANCELLED)
            .select_related("stock_point").prefetch_related("items", "refunds")
        )

        revenue_by_month = {ym: 0 for ym in months}
        for inv in all_invoices:
            if inv.status not in Invoice.SETTLED:
                continue
            key = (inv.date.year, inv.date.month)
            if key in revenue_by_month:
                revenue_by_month[key] += inv.net_total

        by_stock_point = []
        for sp in scope.filter(StockPoint.objects.all(), "id"):
            sp_invoices = [i for i in all_invoices if i.stock_point_id == sp.id]
            sp_paid = [i for i in sp_invoices if i.status in Invoice.SETTLED]
            sp_pending = [i for i in sp_invoices if i.status in Invoice.OUTSTANDING]
            by_stock_point.append({
                "id": sp.slug, "name": sp.name, "kind": sp.kind,
                "invoice_count": len(sp_invoices),
                "revenue_paid": sum(i.net_total for i in sp_paid),
                "pending": sum(i.total for i in sp_pending),
                "units_sold": sum(item.qty for i in sp_invoices for item in i.items.all() if item.item_kind != InvoiceItem.DISCOUNT),
            })
        by_stock_point.sort(key=lambda c: c["revenue_paid"], reverse=True)

        paid_invoices = [i for i in all_invoices if i.status in Invoice.SETTLED]

        return Response({
            "monthly_revenue": [
                {"month": month_label(y, m), "revenue": revenue_by_month[(y, m)]}
                for (y, m) in months
            ],
            "total_revenue_paid": sum(i.net_total for i in paid_invoices),
            "total_invoices": len(paid_invoices),
            "by_stock_point": by_stock_point,
        })


class RentalPortfolioReportView(APIView):
    """
    Task 7: "Rental portfolio (active/closed, churn risk, overdue)" --
    sourced from rentals.Rental and its churn_score property.

    Gated on rentals.view rather than reports.export: the doc lists this
    report's viewers as "Owner, Admin, Sales", and Sales Staff doesn't
    hold reports.export -- but does hold rentals.view, which Owner/Admin
    also hold, so it matches the doc's intended audience here (plus
    Auditor, who holds it too -- consistent with the read-only-everywhere
    role, not contradicted by the doc). This is deliberately a different
    permission than the two reports above; see the module docstring note
    on FinancialSummaryReportView/SalesSummaryReportView.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "rentals.view"

    def get(self, request):
        rentals = list(rental_queryset_for(StoreScope(request.user), Rental.objects.all()).select_related("party"))

        status_counts = {}
        for choice, _ in Rental.STATUS_CHOICES:
            status_counts[choice] = 0
        for r in rentals:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1

        live = [r for r in rentals if r.status in (Rental.APPROVED, Rental.ACTIVE)]
        overdue = [r for r in live if r.next_payment_overdue]

        band_counts = {"High risk": 0, "Watch": 0, "Healthy": 0}
        for r in live:
            band_counts[r.churn_band] += 1

        leaderboard = sorted(live, key=lambda r: r.churn_score, reverse=True)[:20]

        return Response({
            "status_counts": status_counts,
            "live_count": len(live),
            "overdue_count": len(overdue),
            "monthly_recurring_value": sum(r.monthly_fee for r in live),
            "churn_band_counts": band_counts,
            "leaderboard": [
                {
                    "id": r.id, "party": r.party.name, "product": r.product_label,
                    "status": r.status, "score": r.churn_score, "band": r.churn_band,
                    "monthly_fee": r.monthly_fee, "overdue": r.next_payment_overdue,
                }
                for r in leaderboard
            ],
        })


class RepairTurnaroundReportView(APIView):
    """
    Task 7: "Repair turnaround (avg. days Received->Delivered, by
    stage)" -- sourced from repairs.RepairTicket.

    Turnaround is measured as (original settlement invoice's date -
    ticket.received): RepairTicket has no separate "delivered_at"
    timestamp of its own, but ticket.status is set to DELIVERED at the
    exact same moment the original repair invoice is raised in the
    settle() action (see repairs/views.py), so that invoice's date is
    an accurate stand-in -- only counts tickets that have actually been
    settled, not ones just moved to the Delivered stage some other way
    (there isn't one).

    Gated on repairs.view, matching the doc's "Owner, Admin, Repair
    Staff" for this report -- Repair Staff holds repairs.view but not
    reports.export, same reasoning as RentalPortfolioReportView above.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "repairs.view"

    def get(self, request):
        tickets = list(
            StoreScope(request.user).filter(RepairTicket.objects.all(), "stock_point")
            .select_related("stock_point").prefetch_related("invoices")
        )

        stage_counts = {stage: 0 for stage in RepairTicket.STAGES}
        for t in tickets:
            stage_counts[t.status] = stage_counts.get(t.status, 0) + 1

        open_tickets = [t for t in tickets if t.status != RepairTicket.DELIVERED]
        overdue_count = sum(
            1 for t in open_tickets if t.expected and t.expected < date.today()
        )

        turnaround_days = []
        for t in tickets:
            invoice = t.original_invoice
            if invoice:
                turnaround_days.append((invoice.date - t.received).days)

        avg_turnaround = round(sum(turnaround_days) / len(turnaround_days), 1) if turnaround_days else None

        return Response({
            "stage_counts": stage_counts,
            "open_count": len(open_tickets),
            "overdue_count": overdue_count,
            "avg_turnaround_days": avg_turnaround,
            "settled_count": len(turnaround_days),
        })


class PartyReportView(APIView):
    """
    Task 7: "Party / customer report (top customers, new vs. repeat)"
    -- sourced from parties.Party.

    Gated on parties.view. The doc lists this report's viewers as
    "Owner, Admin, Sales", but parties.view is held more broadly in
    this codebase already (Accounts, Repair Staff and Auditor all hold
    it too, for reasons unrelated to this report -- they need party
    contact details for their own modules). Rather than invent a
    narrower permission just for this one report, this reuses the
    existing one; it's a superset of the doc's list, not a mismatch,
    and nothing in it is more sensitive than what those roles already
    see elsewhere (a customer's name and how much they've spent).
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "parties.view"

    def get(self, request):
        # the customer list is shared, but what they spent is counted from
        # this account's store's invoices only
        invoices = StoreScope(request.user).filter(Invoice.objects.prefetch_related("items", "refunds"), "stock_point")
        parties = list(Party.objects.prefetch_related(Prefetch("invoices", queryset=invoices)))

        rows = []
        for p in parties:
            # what they actually paid: settled invoices less refunds
            invoices = [i for i in p.invoices.all() if i.status in Invoice.SETTLED and not i.is_deposit]
            if not invoices:
                continue
            rows.append({
                "id": p.id, "name": p.name, "type": p.type,
                "invoice_count": len(invoices),
                "total_spent": sum(i.net_total for i in invoices),
            })
        rows.sort(key=lambda r: r["total_spent"], reverse=True)

        repeat_count = sum(1 for r in rows if r["invoice_count"] > 1)
        one_time_count = sum(1 for r in rows if r["invoice_count"] == 1)

        return Response({
            "total_parties": len(parties),
            "customers_with_purchases": len(rows),
            "repeat_customers_count": repeat_count,
            "one_time_customers_count": one_time_count,
            "top_customers": rows[:15],
        })


class FeedbackEngagementReportView(APIView):
    """
    Task 7: "Feedback & portal engagement" -- sourced from
    portal.Feedback and portal.PortalAccessLog per the doc.

    Gated on portal.manage, matching the doc's "Owner, Admin" for this
    report exactly -- portal.manage is held by precisely those two
    roles today (owner, manager/"Admin"), nobody else.
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "portal.manage"

    def get(self, request):
        feedback = list(Feedback.objects.select_related("party").order_by("-created_at"))

        rating_counts = {str(i): 0 for i in range(1, 6)}
        for f in feedback:
            key = str(min(5, max(1, f.rating)))
            rating_counts[key] = rating_counts.get(key, 0) + 1
        avg_rating = round(sum(f.rating for f in feedback) / len(feedback), 2) if feedback else None

        months = last_n_months(REPORT_MONTHS)
        range_start = date(months[0][0], months[0][1], 1)
        access_by_month = {ym: 0 for ym in months}
        for log in PortalAccessLog.objects.filter(created_at__date__gte=range_start):
            key = (log.created_at.year, log.created_at.month)
            if key in access_by_month:
                access_by_month[key] += 1

        return Response({
            "feedback_count": len(feedback),
            "avg_rating": avg_rating,
            "rating_counts": rating_counts,
            "recent_feedback": [
                {"party": f.party.name, "rating": f.rating, "comment": f.comment, "created_at": f.created_at}
                for f in feedback[:10]
            ],
            "portal_access_by_month": [
                {"month": month_label(y, m), "count": access_by_month[(y, m)]}
                for (y, m) in months
            ],
            "unique_parties_accessed": PortalAccessLog.objects.values("party_id").distinct().count(),
        })


class InventoryStockReportView(APIView):
    """
    Task 7: "Inventory / stock report" -- sourced from catalog.Stock and
    rentals.RentalAsset per the doc (RentalAsset lives in the rentals
    app in this codebase, not catalog, but it's the same "physical
    laptop tracked individually" concept the doc means).

    Gated on inventory.edit, matching the doc's "Owner, Admin" for this
    report exactly -- inventory.edit is held by precisely those two
    roles today, nobody else (Sales, Repair Staff and Accounts all
    lack it, same as every other inventory-editing view in the app).
    """
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "inventory.edit"

    def get(self, request):
        total_units = 0
        stock_value = 0
        low_stock = []
        by_stock_point = defaultdict(lambda: {"units": 0, "value": 0})

        scope = StoreScope(request.user)
        for p in product_queryset(request.user):
            for v in p.variants.all():
                for s in v.stock.all():
                    total_units += s.quantity
                    stock_value += s.quantity * v.cost
                    by_stock_point[s.stock_point.name]["units"] += s.quantity
                    by_stock_point[s.stock_point.name]["value"] += s.quantity * v.cost
                if scope.assigned and v.total_stock <= 4:
                    low_stock.append({
                        "product": p.display_name, "variant_code": v.code,
                        "spec": v.spec, "total_stock": v.total_stock,
                    })
        low_stock.sort(key=lambda x: x["total_stock"])

        rental_asset_counts = {choice: 0 for choice, _ in RentalAsset.STATUS_CHOICES}
        assets = scope.filter(RentalAsset.objects.all(), "source_stock_point", "returned_to")
        for row in assets.order_by().values("status").annotate(count=Count("id")):
            rental_asset_counts[row["status"]] = row["count"]

        return Response({
            "total_stock_units": total_units,
            "stock_value": stock_value,
            "low_stock_count": len(low_stock),
            "low_stock": low_stock[:20],
            "by_stock_point": [
                {"name": name, "units": v["units"], "value": v["value"]}
                for name, v in sorted(by_stock_point.items(), key=lambda kv: kv[1]["value"], reverse=True)
            ],
            "rental_asset_counts": rental_asset_counts,
        })


# --------------------------------------------------------------------------
# Store-wise Profit & Loss (Store Locator). Formulas and the access rule:
# reports.profit_loss. Authorisation runs before any figure is computed:
#   1. CanViewProfitLoss -- Superuser, or an Admin holding reports.profit_loss
#      (403 for everyone else, logged like any other permission denial)
#   2. StoreScope -- the store asked for must be one this account reaches
#      (403 otherwise, whatever id is sent)
# Responses are marked no-store so no shared cache keeps one account's
# figures for another.
# --------------------------------------------------------------------------

PL_STORE_DENIED = "You can only view Profit & Loss for stores you're assigned to."
PL_PAGE_SIZE, PL_MAX_PAGE_SIZE = 25, 100


def _private(data):
    response = Response(data)
    response["Cache-Control"] = "no-store, private"
    response["Vary"] = "Authorization, Cookie"
    return response


def _pl_meta(period):
    # a period that hasn't ended yet may still be missing expenses (rent,
    # salaries are often entered at month end) -- the dashboard says so
    return {
        "period": {**period.as_dict(), "complete": period.end < timezone.localdate()},
        "generated_at": timezone.now().isoformat(),
        "timezone": timezone.get_current_timezone_name(),
        "currency": "INR",
    }


def _pl_store(request):
    scope = StoreScope(request.user)
    scope.require_assigned()
    values = request.query_params.getlist("store")
    try:
        if len(values) != 1:  # one store per statement -- never "the last of several"
            raise ValueError
        store_id = int(values[0])
    except (TypeError, ValueError):
        raise ValidationError({"store": "Choose one store."})
    if not scope.allows(store_id):
        raise PermissionDenied(PL_STORE_DENIED)
    store = StockPoint.objects.filter(pk=store_id).first()
    if store is None:
        raise NotFound("That store doesn't exist.")
    return store


def _pl_store_info(store):
    return {"id": store.id, "slug": store.slug, "name": store.name, "kind": store.kind, "is_active": store.is_active}


class ProfitLossView(APIView):
    """GET /reports/profit-loss/?store=<id>&period=<key>[&date_from&date_to]
    -- one store's statement, source breakdown, trend and monthly comparison."""
    permission_classes = [permissions.IsAuthenticated, profit_loss.CanViewProfitLoss]

    def get(self, request):
        store = _pl_store(request)
        period = profit_loss.resolve_period(request.query_params)
        figures = profit_loss.raw_figures([store.id], period.start, period.end)[store.id]
        return _private({
            **_pl_meta(period),
            "store": _pl_store_info(store),
            "statement": profit_loss.statement(figures),
            "trend": profit_loss.trend(store.id, period),
            "monthly": profit_loss.monthly_comparison(store.id, period),
        })


class ProfitLossTransactionsView(APIView):
    """GET /reports/profit-loss/transactions/?store=<id>&period=..&kind=settled|refunds|receivables|cancelled
    [&source=sale|repair|rental&page=&page_size=] -- the records behind the totals."""
    permission_classes = [permissions.IsAuthenticated, profit_loss.CanViewProfitLoss]

    def get(self, request):
        store = _pl_store(request)
        period = profit_loss.resolve_period(request.query_params)
        kind = request.query_params.get("kind") or "settled"
        if kind not in profit_loss.TRANSACTION_KINDS:
            raise ValidationError({"kind": f"Choose one of: {', '.join(profit_loss.TRANSACTION_KINDS)}."})
        source = request.query_params.get("source") or None
        if source is not None and source not in profit_loss.SOURCES:
            raise ValidationError({"source": f"Choose one of: {', '.join(profit_loss.SOURCES)}."})
        try:
            page = max(1, int(request.query_params.get("page") or 1))
            page_size = min(PL_MAX_PAGE_SIZE, max(1, int(request.query_params.get("page_size") or PL_PAGE_SIZE)))
        except ValueError:
            raise ValidationError({"page": "Page numbers must be whole numbers."})

        if kind == "refunds":
            qs, serialize = profit_loss.refund_rows(store.id, period, source), profit_loss.serialize_refund
        elif kind == "expenses":
            if not profit_loss.expenses_available():
                return _private({**_pl_meta(period), "store": _pl_store_info(store), "kind": kind, "source": None,
                                 "expenses_available": False, "count": 0, "page": 1, "page_size": page_size, "results": []})
            qs, serialize = profit_loss.expense_list(store.id, period), profit_loss.serialize_expense
        else:
            qs = profit_loss.invoice_rows(store.id, period, kind, source)
            serialize = lambda inv: profit_loss.serialize_invoice(inv, kind)  # noqa: E731
        count = qs.count()
        offset = (page - 1) * page_size
        return _private({
            **_pl_meta(period),
            "store": _pl_store_info(store),
            "kind": kind, "source": source,
            "count": count, "page": page, "page_size": page_size,
            "results": [serialize(row) for row in qs[offset:offset + page_size]],
        })


class ProfitLossStoresView(APIView):
    """GET /reports/profit-loss/stores/?period=.. -- every store this account
    reaches, side by side. The consolidated total is only included for an
    account that sees every store (Superuser / Owner); a store-assigned
    Admin gets their own store's row and nothing else."""
    permission_classes = [permissions.IsAuthenticated, profit_loss.CanViewProfitLoss]

    def get(self, request):
        scope = StoreScope(request.user)
        scope.require_assigned()
        period = profit_loss.resolve_period(request.query_params)
        stores = list(scope.filter(StockPoint.objects.all(), "id"))
        figures = profit_loss.raw_figures([s.id for s in stores], period.start, period.end)

        def summary(statement):
            keys = ("revenue", "cogs", "gross_profit", "gross_margin_pct", "operating_expenses", "other_expenses", "expenses",
                    "net_profit", "net_margin_pct", "transactions", "refunds", "receivables")
            return {**{k: statement[k] for k in keys}, "data_quality": statement["data_quality"]}

        rows = [{"store": _pl_store_info(s), **summary(profit_loss.statement(figures[s.id]))} for s in stores]
        rows.sort(key=lambda r: (-r["revenue"], r["store"]["name"]))
        consolidated = shared = None
        if scope.all:
            # shared / head-office expenses belong to the business, not a store
            shared_fig = profit_loss.shared_figures(period.start, period.end)
            shared = ({k: shared_fig[k] for k in ("operating_expenses", "other_expenses", "expense_count")}
                      if profit_loss.expenses_available() else None)
            consolidated = summary(profit_loss.statement(profit_loss.combine([*figures.values(), shared_fig])))
        return _private({**_pl_meta(period), "can_compare": scope.all, "stores": rows, "shared_expenses": shared,
                         "consolidated": consolidated})
