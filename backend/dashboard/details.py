"""
The records behind each dashboard metric (Dashboard -> click a card).

GET /api/dashboard/detail/<metric>/ with the dashboard's own filters
(date_from, date_to, channel). Each metric re-reads its figure with exactly
the rules DashboardView uses, so the rows always add up to the card:

  revenue_paid     paid product-sale invoices (less refunds)
  repair_revenue   paid repair bills (less refunds)
  pending          unpaid invoices of every kind (sale, repair, rent, on-site)
  stock            stock on hand per product, valued at cost
  low_stock        products with 4 units or fewer
  rental_risk      active rental agreements by churn risk (60+ = at risk)
  rental_pending   rental agreements waiting for the customer's approval
  repair_overdue   open repair jobs past their expected date

Same permission and section gates as the dashboard: a metric from a section
the user's role can't see is a 403, and store staff only ever see their store.
"""
from datetime import date

from django.http import Http404
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm, IsStaffAccount
from accounts.store_scope import StoreScope
from catalog.models import Product, StockPoint
from rentals.models import Rental
from rentals.scope import rental_queryset_for
from repairs.models import RepairTicket
from sales.models import Invoice
from sales.services import mark_overdue

from .layouts import visible_sections

SECTION = {
    "revenue_paid": "sales", "pending": "sales", "repair_revenue": "repairs", "repair_overdue": "repairs",
    "stock": "stock", "low_stock": "stock", "rental_risk": "rentals", "rental_pending": "rentals",
}
LOW_STOCK_AT = 4
MAX_ROWS = 500

MONEY, DATE, TEXT, NUMBER = "money", "date", "text", "number"


def col(key, label, kind=TEXT, align=None):
    return {"key": key, "label": label, "kind": kind, "align": align or ("right" if kind in (MONEY, NUMBER) else "left")}


def _day(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class MetricDetailView(APIView):
    permission_classes = [IsAuthenticated, IsStaffAccount, HasPerm]
    required_perm = "dashboard.view"

    def get(self, request, metric):
        if metric not in SECTION:
            raise Http404("No such dashboard metric.")
        scope = StoreScope(request.user)
        if not scope.assigned or not visible_sections(request.user).get(SECTION[metric]):
            raise PermissionDenied("Your role can't see this figure.")
        self.date_from = _day(request.query_params.get("date_from"))
        self.date_to = _day(request.query_params.get("date_to"))
        channel = request.query_params.get("channel") or None
        if channel == "all":
            channel = None
        if not scope.all:
            channel = StockPoint.objects.get(pk=scope.store_id).slug
        self.channel = channel
        self.scope = scope
        body = getattr(self, f"_{metric}")()
        rows = body["rows"]
        body.update({"metric": metric, "count": len(rows), "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS,
                     "filters": {"date_from": self.date_from and self.date_from.isoformat(),
                                 "date_to": self.date_to and self.date_to.isoformat(), "channel": channel}})
        return Response(body)

    # -- invoices -------------------------------------------------------------
    def _invoices(self):
        qs = (Invoice.objects.exclude(status=Invoice.CANCELLED).filter(is_deposit=False)
              .select_related("party", "stock_point").prefetch_related("items", "refunds").order_by("-date", "-id"))
        if self.date_from:
            qs = qs.filter(date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(date__lte=self.date_to)
        if self.channel:
            qs = qs.filter(stock_point__slug=self.channel)
        return qs

    @staticmethod
    def _invoice_row(inv, amount):
        return {"id": inv.id, "code": inv.code, "date": inv.date, "customer": inv.party.name, "store": inv.stock_point.name,
                "source": inv.get_source_display(), "status": inv.status, "amount": amount,
                "link": f"/sales?invoice={inv.code}"}

    def _revenue_paid(self):
        rows = [self._invoice_row(i, i.net_total) for i in self._invoices().filter(source=Invoice.SALE, status__in=Invoice.SETTLED)]
        return {"title": "Paid sales revenue", "subtitle": "Paid product-sale invoices, less refunds",
                "columns": [col("code", "Invoice"), col("date", "Date", DATE), col("customer", "Customer"), col("store", "Store"),
                            col("amount", "Kept", MONEY)],
                "rows": rows, "total": {"label": "Total", "key": "amount", "value": sum(r["amount"] for r in rows)}, "page": "invoices"}

    def _repair_revenue(self):
        rows = [self._invoice_row(i, i.net_total) for i in self._invoices().filter(source=Invoice.REPAIR, status__in=Invoice.SETTLED)]
        return {"title": "Repair revenue", "subtitle": "Paid repair bills, less refunds",
                "columns": [col("code", "Invoice"), col("date", "Date", DATE), col("customer", "Customer"), col("store", "Store"),
                            col("amount", "Kept", MONEY)],
                "rows": rows, "total": {"label": "Total", "key": "amount", "value": sum(r["amount"] for r in rows)}, "page": "repairs"}

    def _pending(self):
        mark_overdue()
        rows = []
        for inv in self._invoices().filter(status__in=Invoice.OUTSTANDING):
            row = self._invoice_row(inv, inv.total)
            row["due"] = inv.due_date
            rows.append(row)
        return {"title": "Pending collections", "subtitle": "Unpaid invoices of every kind — collect them in Sales & Invoices",
                "columns": [col("code", "Invoice"), col("date", "Date", DATE), col("customer", "Customer"), col("source", "For"),
                            col("status", "Status"), col("due", "Due by", DATE), col("amount", "Amount", MONEY)],
                "rows": rows, "total": {"label": "Total", "key": "amount", "value": sum(r["amount"] for r in rows)}, "page": "invoices"}

    # -- stock ----------------------------------------------------------------
    def _stock_rows(self):
        rows = []
        for p in Product.objects.prefetch_related("variants__stock__stock_point"):
            for v in p.variants.all():
                stock = [s for s in v.stock.all() if not self.channel or s.stock_point.slug == self.channel]
                units = sum(s.quantity for s in stock)
                rows.append({"product": p.display_name, "spec": v.spec, "code": v.code, "units": units, "cost": v.cost,
                             "value": units * v.cost,
                             "where": ", ".join(f"{s.stock_point.name} {s.quantity}" for s in stock if s.quantity) or "—"})
        return rows

    def _stock(self):
        rows = sorted((r for r in self._stock_rows() if r["units"]), key=lambda r: -r["value"])
        return {"title": "Stock on hand", "subtitle": "Every product in stock, valued at its purchase cost",
                "columns": [col("product", "Product"), col("spec", "Spec"), col("where", "Where"), col("units", "Units", NUMBER),
                            col("cost", "Cost / unit", MONEY), col("value", "Value at cost", MONEY)],
                "rows": rows, "total": {"label": f"{sum(r['units'] for r in rows)} units", "key": "value", "value": sum(r["value"] for r in rows)},
                "page": "inventory"}

    def _low_stock(self):
        rows = sorted((r for r in self._stock_rows() if r["units"] <= LOW_STOCK_AT), key=lambda r: (r["units"], r["product"]))
        return {"title": "Low stock alerts", "subtitle": f"Products with {LOW_STOCK_AT} units or fewer — time to reorder",
                "columns": [col("product", "Product"), col("spec", "Spec"), col("code", "SKU"), col("where", "Where"),
                            col("units", "Units left", NUMBER)],
                "rows": rows, "total": None, "page": "inventory"}

    # -- rentals --------------------------------------------------------------
    def _rental_risk(self):
        rentals = list(rental_queryset_for(self.scope, Rental.objects.all()).select_related("party")
                       .prefetch_related("issues", "lines").filter(status__in=[Rental.APPROVED, Rental.ACTIVE]))
        rentals.sort(key=lambda r: -r.churn_score)
        rows = [{"id": r.id, "agreement": r.agreement_code or f"#{r.id}", "customer": r.party.name, "product": r.product_label,
                 "score": r.churn_score, "band": r.churn_band, "late": r.late_count,
                 "open_issues": sum(1 for i in r.issues.all() if i.status != "Resolved"), "at_risk": r.churn_score >= 60,
                 "link": "/rentals"} for r in rentals]
        return {"title": "Rental churn risk", "subtitle": "Active agreements, riskiest first — 60 or more counts as at risk",
                "columns": [col("agreement", "Agreement"), col("customer", "Customer"), col("product", "Devices"),
                            col("late", "Late payments", NUMBER), col("open_issues", "Open problems", NUMBER), col("score", "Risk score", NUMBER),
                            col("band", "Risk")],
                "rows": rows, "total": {"label": "At risk", "key": "score", "value": sum(1 for r in rows if r["at_risk"]), "plain": True},
                "page": "rentals"}

    def _rental_pending(self):
        rentals = (rental_queryset_for(self.scope, Rental.objects.all()).select_related("party")
                   .filter(status=Rental.PENDING_APPROVAL).order_by("start"))
        rows = [{"id": r.id, "agreement": r.agreement_code or f"#{r.id}", "customer": r.party.name, "phone": r.party.phone,
                 "product": r.product_label, "start": r.start, "monthly": r.total_monthly_fee, "link": "/rentals"} for r in rentals]
        return {"title": "Pending rental approvals", "subtitle": "Agreements sent to the customer and not yet approved",
                "columns": [col("agreement", "Agreement"), col("customer", "Customer"), col("phone", "Phone"), col("product", "Devices"),
                            col("start", "Starts", DATE), col("monthly", "Monthly rent", MONEY)],
                "rows": rows, "total": None, "page": "rentals"}

    # -- repairs --------------------------------------------------------------
    def _repair_overdue(self):
        tickets = (self.scope.filter(RepairTicket.objects.all(), "stock_point").select_related("party", "assigned_to", "stock_point")
                   .exclude(status=RepairTicket.DELIVERED).filter(expected__isnull=False, expected__lt=date.today()).order_by("expected"))
        today = date.today()
        rows = [{"id": t.id, "code": t.code, "customer": t.party.name, "device": f"{t.brand} {t.model_name}".strip(),
                 "status": t.status, "expected": t.expected, "late_days": (today - t.expected).days,
                 "staff": (t.assigned_to.get_full_name() or t.assigned_to.username) if t.assigned_to else "Not assigned",
                 "link": "/repairs"} for t in tickets]
        return {"title": "Overdue repairs", "subtitle": "Open jobs past their expected delivery date",
                "columns": [col("code", "Job"), col("customer", "Customer"), col("device", "Device"), col("status", "Stage"),
                            col("staff", "Repair staff"), col("expected", "Expected", DATE), col("late_days", "Days late", NUMBER)],
                "rows": rows, "total": None, "page": "repairs"}
