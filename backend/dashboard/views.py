from collections import defaultdict
from datetime import date

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffAccount
from catalog.models import Product, StockPoint
from rentals.models import Rental
from repairs.models import RepairTicket
from sales.models import Invoice

from .layouts import effective_layout, visible_sections


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _last_n_months(n):
    """Last n calendar months including the current one, oldest first,
    as (year, month) tuples -- e.g. n=6 in October 2026 gives May..Oct."""
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(months))


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

        # Per-role dashboard: each section only runs its (sometimes
        # expensive) query and appears in the response if the signed-in
        # user actually holds the permission for that domain -- the same
        # gate the widget layout uses, see dashboard.layouts.
        sections = visible_sections(request.user)
        show_stock_section = sections["stock"]
        can_sales = sections["sales"]
        can_repairs = sections["repairs"]
        can_rentals = sections["rentals"]

        response = {
            "filters_applied": {
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "channel": channel_slug,
            },
            "sections": sections,
        }

        if show_stock_section:
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
            response.update({
                "total_stock_units": total_units,
                "stock_value": stock_value,
                "low_stock": low_stock,
                "low_stock_count": len(low_stock),
            })

        if can_sales:
            # -- invoices: date range + channel both apply here --
            all_invoices = Invoice.objects.select_related("stock_point").prefetch_related("items")
            if date_from:
                all_invoices = all_invoices.filter(date__gte=date_from)
            if date_to:
                all_invoices = all_invoices.filter(date__lte=date_to)
            if channel_slug:
                all_invoices = all_invoices.filter(stock_point__slug=channel_slug)
            all_invoices = list(all_invoices)

            # Every invoice -- sale, repair or rent -- is collected through
            # Sales & Invoices, so pending collections cover all of them;
            # "sales revenue" and the channel breakdown stay product sales.
            sale_invoices = [i for i in all_invoices if i.source == Invoice.SALE]
            revenue_paid = [i for i in sale_invoices if i.status == Invoice.PAID]
            revenue_paid_total = sum(i.total for i in revenue_paid)
            pending = [i for i in all_invoices if i.status != Invoice.PAID]
            pending_total = sum(i.total for i in pending)

            # sales broken out per channel, respecting the same date filter --
            # every shop and every online channel counted separately, so
            # "shop-wise" and "website-wise" numbers are both just filters
            # on the same underlying data. If a specific channel was picked,
            # only that one row comes back.
            channel_sales = []
            stock_points = StockPoint.objects.filter(slug=channel_slug) if channel_slug else StockPoint.objects.all()
            for sp in stock_points:
                sp_invoices = [i for i in sale_invoices if i.stock_point_id == sp.id]
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

            response.update({
                "revenue_paid": revenue_paid_total,
                "pending_collections": pending_total,
                "open_invoice_count": len(pending),
                "channel_sales": channel_sales,
            })

            # Task 4 "revenue by period" widget (the Accounts role's
            # dashboard, and useful for Owner/Admin too) -- a real trend
            # from paid invoices + paid repair bills, replacing the
            # frontend's placeholder demo series. Independent of the
            # date_from/date_to/channel filters above, like rentals/churn
            # below -- this chart's whole point is the last several
            # months at a glance, not one filtered slice of them.
            months = _last_n_months(6)
            range_start = date(months[0][0], months[0][1], 1)
            by_month = {source: defaultdict(int) for source, _ in Invoice.SOURCE_CHOICES}
            for inv in Invoice.objects.filter(status=Invoice.PAID, date__gte=range_start).prefetch_related("items"):
                by_month[inv.source][(inv.date.year, inv.date.month)] += inv.total
            response["monthly_revenue"] = [
                {
                    "month": f"{MONTH_ABBR[m]} {y}",
                    "sales": by_month[Invoice.SALE].get((y, m), 0),
                    "repairs": by_month[Invoice.REPAIR].get((y, m), 0),
                    "rentals": by_month[Invoice.RENTAL].get((y, m), 0),
                }
                for (y, m) in months
            ]

        if can_repairs:
            # repair income: the repair-sourced invoices in the shared ledger,
            # kept separate from product sales revenue
            repair_invoices = Invoice.objects.filter(source=Invoice.REPAIR).prefetch_related("items")
            if date_from:
                repair_invoices = repair_invoices.filter(date__gte=date_from)
            if date_to:
                repair_invoices = repair_invoices.filter(date__lte=date_to)
            if channel_slug:
                repair_invoices = repair_invoices.filter(stock_point__slug=channel_slug)
            response.update({
                "repair_revenue_paid": sum(ri.total for ri in repair_invoices.filter(status=Invoice.PAID)),
                "repair_invoice_count": repair_invoices.count(),
            })

            # Task 4, Repair Staff widget: "ticket queue by stage, overdue
            # tickets" -- not date/channel filtered like the invoice figures
            # above, this is "what's in the shop right now" regardless of
            # when it came in.
            open_tickets = RepairTicket.objects.exclude(status=RepairTicket.DELIVERED)
            response.update({
                "repair_stage_counts": {
                    stage: RepairTicket.objects.filter(status=stage).count() for stage in RepairTicket.STAGES
                },
                "repair_overdue_count": open_tickets.filter(expected__isnull=False, expected__lt=date.today()).count(),
            })

        if can_rentals:
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

            response.update({
                "rentals_at_risk": sum(1 for r in rentals if r.churn_score >= 60),
                "rental_count": len(rentals),
                "rental_device_count": sum(max(1, len(r.lines.all())) for r in rentals),
                "churn_leaderboard": churn_leaderboard,
                "recurring_issues_by_unit": recurring_by_unit,
                "recurring_issues_by_model": recurring_by_model,
                # Task 4, Sales Staff widget: "rental agreements pending
                # approval" -- global count, not scoped to the approved/
                # active rentals list above (this is specifically the
                # ones still waiting on a customer decision).
                "rentals_pending_approval": Rental.objects.filter(status=Rental.PENDING_APPROVAL).count(),
            })

        return Response(response)


class DashboardLayoutView(APIView):
    """
    The signed-in user's dashboard elements: which widgets, in what
    order and size, already narrowed to the sections their role can see.
    Pairs with DashboardView -- this says *what* to draw, summary/ holds
    the figures each widget's data_keys point into.
    """
    permission_classes = [IsAuthenticated, IsStaffAccount]

    def get(self, request):
        return Response(effective_layout(request.user))
