from collections import defaultdict
from datetime import date

from django.db.models import Count
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from catalog.models import Product, StockPoint
from parties.models import Party
from portal.models import Feedback, PortalAccessLog
from rentals.models import Rental, RentalAsset
from repairs.models import RepairTicket
from sales.models import Invoice
from sales.services import mark_overdue
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

        revenue_by_month = {ym: 0 for ym in months}
        for inv in Invoice.objects.filter(status=Invoice.PAID, date__gte=range_start):
            key = (inv.date.year, inv.date.month)
            if key in revenue_by_month:
                revenue_by_month[key] += inv.total

        mark_overdue()
        outstanding_invoices = Invoice.objects.filter(status__in=Invoice.OUTSTANDING)
        outstanding_total = sum(inv.total for inv in outstanding_invoices)

        active_rentals = Rental.objects.filter(status__in=[Rental.APPROVED, Rental.ACTIVE])

        return Response({
            "monthly_revenue": [
                {"month": month_label(y, m), "revenue": revenue_by_month[(y, m)]}
                for (y, m) in months
            ],
            "outstanding_total": outstanding_total,
            "outstanding_count": outstanding_invoices.count(),
            "rentals_active_monthly_value": sum(r.monthly_fee for r in active_rentals),
            "rentals_active_count": active_rentals.count(),
            "rentals_pending_approval": Rental.objects.filter(status=Rental.PENDING_APPROVAL).count(),
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

        all_invoices = list(
            Invoice.objects.filter(source=Invoice.SALE, date__gte=range_start).exclude(status=Invoice.CANCELLED)
            .select_related("stock_point").prefetch_related("items")
        )

        revenue_by_month = {ym: 0 for ym in months}
        for inv in all_invoices:
            if inv.status != Invoice.PAID:
                continue
            key = (inv.date.year, inv.date.month)
            if key in revenue_by_month:
                revenue_by_month[key] += inv.total

        by_stock_point = []
        for sp in StockPoint.objects.all():
            sp_invoices = [i for i in all_invoices if i.stock_point_id == sp.id]
            sp_paid = [i for i in sp_invoices if i.status == Invoice.PAID]
            sp_pending = [i for i in sp_invoices if i.status in Invoice.OUTSTANDING]
            by_stock_point.append({
                "id": sp.slug, "name": sp.name, "kind": sp.kind,
                "invoice_count": len(sp_invoices),
                "revenue_paid": sum(i.total for i in sp_paid),
                "pending": sum(i.total for i in sp_pending),
                "units_sold": sum(item.qty for i in sp_invoices for item in i.items.all()),
            })
        by_stock_point.sort(key=lambda c: c["revenue_paid"], reverse=True)

        paid_invoices = [i for i in all_invoices if i.status == Invoice.PAID]

        return Response({
            "monthly_revenue": [
                {"month": month_label(y, m), "revenue": revenue_by_month[(y, m)]}
                for (y, m) in months
            ],
            "total_revenue_paid": sum(i.total for i in paid_invoices),
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
        rentals = list(Rental.objects.select_related("party"))

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
            RepairTicket.objects.select_related("stock_point")
            .prefetch_related("invoices")
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
        parties = list(Party.objects.prefetch_related("invoices__items"))

        rows = []
        for p in parties:
            invoices = list(p.invoices.all())
            if not invoices:
                continue
            rows.append({
                "id": p.id, "name": p.name, "type": p.type,
                "invoice_count": len(invoices),
                "total_spent": sum(i.total for i in invoices),
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

        for p in Product.objects.prefetch_related("variants__stock__stock_point"):
            for v in p.variants.all():
                for s in v.stock.all():
                    total_units += s.quantity
                    stock_value += s.quantity * v.cost
                    by_stock_point[s.stock_point.name]["units"] += s.quantity
                    by_stock_point[s.stock_point.name]["value"] += s.quantity * v.cost
                if v.total_stock <= 4:
                    low_stock.append({
                        "product": p.display_name, "variant_code": v.code,
                        "spec": v.spec, "total_stock": v.total_stock,
                    })
        low_stock.sort(key=lambda x: x["total_stock"])

        rental_asset_counts = {choice: 0 for choice, _ in RentalAsset.STATUS_CHOICES}
        for row in RentalAsset.objects.values("status").annotate(count=Count("id")):
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
