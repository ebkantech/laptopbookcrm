"""
The records behind each dashboard metric (Dashboard -> click a card).

GET /api/dashboard/detail/<metric>/ with the dashboard's own filters
(date_from, date_to, channel). Each metric re-reads its figure with exactly
the rules DashboardView uses, so the rows always add up to the card:

  revenue_paid     paid product-sale invoices (less refunds)
  repair_revenue   paid repair bills (less refunds)
  pending          customers with unpaid invoices (sale, repair, rent, on-site), with
                   their phone and a WhatsApp reminder ready to copy
  stock            stock on hand per product, valued at cost
  low_stock        products with 4 units or fewer
  rental_risk      active rental agreements by churn risk (60+ = at risk)
  rental_pending   rental agreements waiting for the customer's approval
  repair_overdue   open repair jobs past their expected date

Same permission and section gates as the dashboard: a metric from a section
the user's role can't see is a 403, and store staff only ever see their store.

Paged: ?page=1&page_size=50 (at most 200 a page). The invoice lists are paged
in the database and their totals are summed there too, so a year of sales
never has to be loaded to show one page. "count" and "total" always cover
every matching record, not just the page.
"""
from datetime import date

from django.db.models import F, Sum
from django.http import Http404
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm, IsStaffAccount
from accounts.store_scope import StoreScope
from branding import texts
from catalog.models import Product, StockPoint
from rentals.models import Rental
from rentals.scope import rental_queryset_for
from repairs.models import RepairTicket
from sales.models import Invoice, InvoiceItem, Refund
from sales.services import mark_overdue

from .layouts import visible_sections

SECTION = {
    "revenue_paid": "sales", "pending": "sales", "repair_revenue": "repairs", "repair_overdue": "repairs",
    "stock": "stock", "low_stock": "stock", "rental_risk": "rentals", "rental_pending": "rentals",
}
LOW_STOCK_AT = 4
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

MONEY, DATE, TEXT, NUMBER = "money", "date", "text", "number"


def col(key, label, kind=TEXT, align=None):
    return {"key": key, "label": label, "kind": kind, "align": align or ("right" if kind in (MONEY, NUMBER) else "left")}


def _whole(value, default, low, high):
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def rupees(amount):
    """45,499 / 1,06,799 -- Indian digit grouping, as customers read it."""
    digits = str(int(amount))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups) + "," + tail


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
        self.page_size = _whole(request.query_params.get("page_size"), PAGE_SIZE, 1, MAX_PAGE_SIZE)
        page = _whole(request.query_params.get("page"), 1, 1, 10**6)
        body = getattr(self, f"_{metric}")()
        if "rows" in body:  # small lists, built whole: page them here
            count = len(body["rows"])
            pages = max(1, -(-count // self.page_size))
            page = min(page, pages)
            body["rows"] = body["rows"][(page - 1) * self.page_size: page * self.page_size]
        else:  # big lists: the metric reads just one page from the database
            count = body.pop("count")
            pages = max(1, -(-count // self.page_size))
            page = min(page, pages)
            body["rows"] = body.pop("page_rows")((page - 1) * self.page_size, page * self.page_size)
        body.update({"metric": metric, "count": count, "page_number": page, "pages": pages, "page_size": self.page_size,
                     "truncated": False,
                     "filters": {"date_from": self.date_from and self.date_from.isoformat(),
                                 "date_to": self.date_to and self.date_to.isoformat(), "channel": channel}})
        return Response(body)

    # -- invoices -------------------------------------------------------------
    def _invoices(self):
        qs = Invoice.objects.exclude(status=Invoice.CANCELLED).filter(is_deposit=False).order_by("-date", "-id")
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

    @staticmethod
    def _kept(qs):
        """Sum of (invoice total - refunds) over the invoices, in the database."""
        ids = qs.order_by().values("id")
        billed = InvoiceItem.objects.filter(invoice__in=ids).aggregate(v=Sum(F("qty") * F("price")))["v"] or 0
        refunded = Refund.objects.filter(invoice__in=ids).aggregate(v=Sum("amount"))["v"] or 0
        return billed - refunded

    def _paid_list(self, source, title, subtitle, page):
        qs = self._invoices().filter(source=source, status__in=Invoice.SETTLED)

        def page_rows(start, end):
            chunk = qs.select_related("party", "stock_point").prefetch_related("items", "refunds")[start:end]
            return [self._invoice_row(i, i.net_total) for i in chunk]

        return {"title": title, "subtitle": subtitle,
                "columns": [col("code", "Invoice"), col("date", "Date", DATE), col("customer", "Customer"), col("store", "Store"),
                            col("amount", "Kept", MONEY)],
                "count": qs.count(), "page_rows": page_rows,
                "total": {"label": "Total", "key": "amount", "value": self._kept(qs)}, "page": page}

    def _revenue_paid(self):
        return self._paid_list(Invoice.SALE, "Paid sales revenue", "Paid product-sale invoices, less refunds", "invoices")

    def _repair_revenue(self):
        return self._paid_list(Invoice.REPAIR, "Repair revenue", "Paid repair bills, less refunds", "repairs")

    def _pending(self):
        """One row per customer who owes money: who they are, how to reach
        them, which invoices are unpaid, and a WhatsApp reminder to copy.
        The total is the card's figure (the unpaid invoices' full amounts);
        "Still to pay" also takes off any part payments already received."""
        mark_overdue()
        open_ids = self._invoices().filter(status__in=Invoice.OUTSTANDING).order_by().values("id")
        billed = (InvoiceItem.objects.filter(invoice__in=open_ids).values("invoice__party")
                  .annotate(v=Sum(F("qty") * F("price"))).order_by())
        by_party = {r["invoice__party"]: r["v"] or 0 for r in billed}
        # customers with no line items still owe nothing, but keep them listed
        for pid in Invoice.objects.filter(id__in=open_ids).values_list("party", flat=True).distinct():
            by_party.setdefault(pid, 0)
        order = sorted(by_party, key=lambda pid: (-by_party[pid], pid))
        today = date.today()

        def page_rows(start, end):
            ids = order[start:end]
            invoices = (Invoice.objects.filter(id__in=open_ids, party__in=ids).select_related("party")
                        .prefetch_related("items", "part_payments").order_by("due_date", "date", "id"))
            grouped = {}
            for inv in invoices:
                grouped.setdefault(inv.party_id, []).append(inv)
            rows = []
            for pid in ids:
                invs = grouped.get(pid, [])
                if not invs:
                    continue
                party = invs[0].party
                balance = sum(i.balance_due for i in invs)
                dues = [i.due_date for i in invs if i.due_date]
                oldest = min(dues) if dues else None
                late = sum(1 for i in invs if i.status == Invoice.OVERDUE)
                listed = "; ".join(
                    f"{i.code} (Rs {rupees(i.balance_due)}{f', due {i.due_date:%d %b %Y}' if i.due_date else ''})" for i in invs)
                reminder = texts.message("payment_reminder", customer=party.name, amount=rupees(balance), invoices=listed,
                                         count=len(invs))
                rows.append({
                    "id": pid, "customer": party.name, "phone": party.phone, "email": party.email, "city": party.city,
                    "kind": party.get_type_display(), "invoices": ", ".join(i.code for i in invs), "invoice_count": len(invs),
                    "oldest_due": oldest, "days_late": (today - oldest).days if oldest and oldest < today else 0,
                    "overdue": late, "status": "Overdue" if late else "Due",
                    "balance": balance, "amount": by_party[pid],
                    "link": f"/sales?party={pid}&due=1",
                    "copy": [{"label": "Copy reminder", "text": reminder, "primary": True},
                             {"label": "Copy phone", "text": party.phone}] if party.phone else
                            [{"label": "Copy reminder", "text": reminder, "primary": True}],
                })
            return rows

        return {"title": "Pending collections",
                "subtitle": "Customers with unpaid invoices, most owed first — copy a reminder and send it on WhatsApp",
                "columns": [col("customer", "Customer"), col("phone", "Phone"), col("invoices", "Unpaid invoices"),
                            col("oldest_due", "Oldest due", DATE), col("status", "Status"),
                            col("balance", "Still to pay", MONEY), col("amount", "Invoiced", MONEY)],
                "count": len(order), "page_rows": page_rows, "row_actions": True,
                "total": {"label": "Total", "key": "amount", "value": sum(by_party.values())}, "page": "invoices"}

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
