from collections import defaultdict
from datetime import date

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffAccount
from catalog.models import Product, StockPoint
from rentals.models import Rental
from repairs.models import RepairInvoice
from sales.models import Invoice


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class DashboardView(APIView):
    """
    One call, everything the BI overview needs: KPI strip, low-stock
    list, rental churn leaderboard, and a sales breakdown per channel.

    Accepts optional filters, applied to every sales-derived figure
    (revenue, pending collections, channel breakdown) and to the stock
    snapshot when a channel is picked:
      - date_from / date_to (YYYY-MM-DD) -- filters invoices by date
      - channel (a StockPoint slug, e.g. 'kb', 'amazon') -- scopes
        revenue to that one channel, and stock figures to that one
        shop/warehouse's shelf, instead of every location combined

    Rentals/churn aren't tied to a sales channel or invoice date, so
    that section stays global regardless of these filters.
    """
    permission_classes = [IsAuthenticated, IsStaffAccount]

    def get(self, request):
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        channel_slug = request.query_params.get("channel") or None
        if channel_slug == "all":
            channel_slug = None

        # -- stock snapshot: scoped to one channel's shelf if picked, otherwise every location --
        products = Product.objects.prefetch_related("variants__stock__stock_point").all()
        total_units = 0
        stock_value = 0
        low_stock = []
        for p in products:
            for v in p.variants.all():
                rows = v.stock.all()
                if channel_slug:
                    rows = [s for s in rows if s.stock_point.slug == channel_slug]
                total = sum(s.quantity for s in rows)
                total_units += total
                stock_value += total * v.cost
                if total <= 4:
                    low_stock.append({
                        "product": p.display_name, "variant_code": v.code,
                        "spec": v.spec, "total_stock": total,
                    })

        # -- invoices: date range + channel both apply here --
        all_invoices = Invoice.objects.select_related("stock_point").prefetch_related("items")
        if date_from:
            all_invoices = all_invoices.filter(date__gte=date_from)
        if date_to:
            all_invoices = all_invoices.filter(date__lte=date_to)
        if channel_slug:
            all_invoices = all_invoices.filter(stock_point__slug=channel_slug)
        all_invoices = list(all_invoices)

        revenue_paid = [i for i in all_invoices if i.status == Invoice.PAID]
        revenue_paid_total = sum(i.total for i in revenue_paid)
        pending = [i for i in all_invoices if i.status != Invoice.PAID]
        pending_total = sum(i.total for i in pending)

        # repair income, tracked separately from product sales revenue --
        # was previously invisible outside the Repairs module entirely,
        # since RepairInvoice is a wholly separate table from sales.Invoice
        repair_invoices = RepairInvoice.objects.select_related("stock_point").all()
        if date_from:
            repair_invoices = repair_invoices.filter(date__gte=date_from)
        if date_to:
            repair_invoices = repair_invoices.filter(date__lte=date_to)
        if channel_slug:
            repair_invoices = repair_invoices.filter(stock_point__slug=channel_slug)
        repair_revenue_paid = sum(ri.amount for ri in repair_invoices.filter(status="Paid"))
        repair_invoice_count = repair_invoices.count()

        # sales broken out per channel, respecting the same date filter --
        # every shop and every online channel counted separately, so
        # "shop-wise" and "website-wise" numbers are both just filters
        # on the same underlying data. If a specific channel was picked,
        # only that one row comes back.
        channel_sales = []
        stock_points = StockPoint.objects.filter(slug=channel_slug) if channel_slug else StockPoint.objects.all()
        for sp in stock_points:
            sp_invoices = [i for i in all_invoices if i.stock_point_id == sp.id]
            sp_paid = [i for i in sp_invoices if i.status == Invoice.PAID]
            sp_pending = [i for i in sp_invoices if i.status != Invoice.PAID]
            channel_sales.append({
                "id": sp.slug, "name": sp.name, "kind": sp.kind,
                "invoice_count": len(sp_invoices),
                "revenue_paid": sum(i.total for i in sp_paid),
                "pending": sum(i.total for i in sp_pending),
                "units_sold": sum(item.qty for i in sp_invoices for item in i.items.all()),
            })
        channel_sales.sort(key=lambda c: c["revenue_paid"], reverse=True)

        # -- rentals/churn: global, not affected by the date/channel filters above --
        rentals = list(
            Rental.objects.select_related("party")
            .prefetch_related("issues", "lines")
            .filter(status__in=[Rental.APPROVED, Rental.ACTIVE])
        )
        rentals.sort(key=lambda r: r.churn_score, reverse=True)
        churn_leaderboard = [
            {
                "party": r.party.name, "product": r.product_label,
                "score": r.churn_score, "band": r.churn_band,
            }
            for r in rentals[:5]
        ]

        recurring_by_unit = []
        for r in rentals:
            issues = list(r.issues.all())
            if len(issues) >= 2:
                recurring_by_unit.append({
                    "rental_id": r.id, "party": r.party.name, "product": r.product_label,
                    "issue_count": len(issues),
                    "open_count": sum(1 for i in issues if i.status != "Resolved"),
                    "latest_issue": max(issues, key=lambda i: i.raised_at).title,
                })
        recurring_by_unit.sort(key=lambda x: x["issue_count"], reverse=True)

        model_groups = defaultdict(list)
        for r in rentals:
            model_groups[r.product_label].extend(r.issues.all())
        recurring_by_model = [
            {
                "product": model, "issue_count": len(issues),
                "affected_units": len({i.rental_id for i in issues}),
                "open_count": sum(1 for i in issues if i.status != "Resolved"),
            }
            for model, issues in model_groups.items() if len(issues) >= 2
        ]
        recurring_by_model.sort(key=lambda x: x["issue_count"], reverse=True)

        return Response({
            "filters_applied": {
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "channel": channel_slug,
            },
            "total_stock_units": total_units,
            "stock_value": stock_value,
            "low_stock": low_stock,
            "low_stock_count": len(low_stock),
            "revenue_paid": revenue_paid_total,
            "repair_revenue_paid": repair_revenue_paid,
            "repair_invoice_count": repair_invoice_count,
            "pending_collections": pending_total,
            "open_invoice_count": len(pending),
            "rentals_at_risk": sum(1 for r in rentals if r.churn_score >= 60),
            "rental_count": len(rentals),
            "rental_device_count": sum(max(1, len(r.lines.all())) for r in rentals),
            "churn_leaderboard": churn_leaderboard,
            "channel_sales": channel_sales,
            "recurring_issues_by_unit": recurring_by_unit,
            "recurring_issues_by_model": recurring_by_model,
        })
