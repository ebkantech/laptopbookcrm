"""Store-wise Profit & Loss (reports.profit_loss): figures, periods and access."""
from datetime import date

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import PermissionDeniedLog
from catalog.models import Product, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from reports.profit_loss import resolve_period
from sales.models import Invoice
from sales.services import cancel_invoice, create_invoice, refund_invoice

PL = "/api/reports/profit-loss/"
TX = "/api/reports/profit-loss/transactions/"
STORES = "/api/reports/profit-loss/stores/"
SEPT = {"period": "custom", "date_from": "2026-09-01", "date_to": "2026-09-30"}
ADMIN = ["roles.manage", "reports.profit_loss"]


class ProfitLossTestBase(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543211", joined=date(2026, 1, 1))
        product = Product.objects.create(model_name="Laptop", product_code="P-1")
        self.a = Variant.objects.create(product=product, code="V-A", spec="8GB", mrp=45000, sell_price=40000, cost=30000)
        self.b = Variant.objects.create(product=product, code="V-B", spec="16GB", mrp=55000, sell_price=50000, cost=35000)
        self.superuser = make_user("root", superuser=True)

    def invoice(self, store, day, lines, status=Invoice.PAID, source=Invoice.SALE, **extra):
        return create_invoice(lines=lines, party=self.party, stock_point=store, date=day, status=status, source=source,
                              pay_method="Cash" if status == Invoice.PAID else "", **extra)

    def sale_line(self, variant, qty, price=None):
        return {"variant": variant, "qty": qty, "price": variant.sell_price if price is None else price}

    def get(self, client, url, store=None, **params):
        if store is not None:
            params["store"] = store.id
        return client.get(url, params)


class ProfitLossFigureTests(ProfitLossTestBase):
    """Karol Bagh, September 2026 -- every case the statement has to get right."""

    def setUp(self):
        super().setUp()
        kb = self.kb
        # S1: 2 x A + 1 x B; one A returned and put back on the shelf
        self.s1 = self.invoice(kb, date(2026, 9, 5), [self.sale_line(self.a, 2), self.sale_line(self.b, 1)])
        line_a = self.s1.items.get(variant=self.a)
        refund_invoice(self.s1, self.superuser, method="Cash", reason="Returned", items=[{"item": line_a.id, "qty": 1}], restock=True)
        # S2: B sold at a discount, returned damaged (not restocked) -- fully refunded
        self.s2 = self.invoice(kb, date(2026, 9, 10), [self.sale_line(self.b, 1, price=48000)])
        line_b = self.s2.items.get()
        refund_invoice(self.s2, self.superuser, method="Cash", reason="Damaged", items=[{"item": line_b.id, "qty": 1}], restock=False)
        # unpaid and cancelled sales: not revenue
        self.invoice(kb, date(2026, 9, 12), [self.sale_line(self.a, 1)], status=Invoice.LINK_SENT)
        cancelled = self.invoice(kb, date(2026, 9, 15), [self.sale_line(self.a, 1)], status=Invoice.LINK_SENT)
        cancel_invoice(cancelled, self.superuser, "Raised by mistake")
        # repair: advance + final bill that deducts it (counted once)
        self.invoice(kb, date(2026, 9, 3), [{"description": "Advance", "qty": 1, "price": 2000}], source=Invoice.REPAIR, is_advance=True)
        self.invoice(kb, date(2026, 9, 20), [
            {"description": "Screen replacement", "qty": 1, "price": 9000},
            {"description": "Less: advance received", "qty": 1, "price": -2000},
        ], source=Invoice.REPAIR)
        # rent
        self.invoice(kb, date(2026, 9, 1), [{"description": "Rent Sep", "qty": 1, "price": 3000}], source=Invoice.RENTAL)
        # outside the period, and at the other store
        self.invoice(kb, date(2026, 8, 31), [self.sale_line(self.a, 1)])
        self.invoice(kb, date(2026, 10, 1), [self.sale_line(self.a, 1)])
        self.invoice(self.np, date(2026, 9, 5), [self.sale_line(self.a, 1)])
        self.client = client_for(self.superuser)

    def statement(self, store=None, **params):
        response = self.get(self.client, PL, store or self.kb, **(params or SEPT))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_statement_figures(self):
        st = self.statement()["statement"]
        self.assertEqual(st["billed"], 130000 + 48000 + 2000 + 7000 + 3000)
        self.assertEqual(st["refunds"], 40000 + 48000)
        self.assertEqual(st["revenue"], 102000)
        # (2 x 30000 + 35000) + 35000 - 30000 restocked; the damaged unit stays in COGS
        self.assertEqual(st["cogs"], 100000)
        self.assertEqual(st["gross_profit"], 2000)
        self.assertEqual(st["gross_margin_pct"], "2.0")
        self.assertEqual(st["transactions"], 5)
        self.assertEqual(st["refund_count"], 2)
        self.assertEqual(st["receivables"], {"amount": 40000, "count": 1})
        self.assertEqual(st["cancelled"], {"amount": 40000, "count": 1})

    def test_breakdown_by_source_and_product_loss(self):
        rows = {r["source"]: r for r in self.statement()["statement"]["by_source"]}
        self.assertEqual((rows["sale"]["revenue"], rows["sale"]["cogs"], rows["sale"]["gross_profit"]), (90000, 100000, -10000))
        self.assertEqual(rows["sale"]["gross_margin_pct"], "-11.1")
        self.assertEqual((rows["repair"]["revenue"], rows["repair"]["invoices"]), (9000, 2))
        self.assertIsNone(rows["repair"]["cogs"])
        self.assertEqual(rows["rental"]["revenue"], 3000)

    def test_no_expense_records_is_unavailable_not_zero(self):
        data = self.statement()
        st = data["statement"]
        self.assertEqual(st["expense_count"], 0)
        for key in ("operating_expenses", "other_expenses", "expenses", "net_profit", "net_margin_pct"):
            self.assertIsNone(st[key], key)
        quality = st["data_quality"]
        self.assertEqual(quality["expense_status"], "none_recorded")
        # every product sold has a real cost; repair labour and rent carry no goods cost by nature
        self.assertTrue(quality["cogs_complete"])
        self.assertEqual(quality["reliability"], "complete")
        self.assertEqual(quality["uncosted_revenue"], 9000 + 3000)
        self.assertEqual(quality["cost_basis"], "locked_at_sale")
        self.assertTrue(quality["expenses_tracked"])
        self.assertFalse(quality["expenses_recorded"])
        self.assertFalse(quality["tax_tracked"])
        self.assertTrue(all(p["net_profit"] is None and p["expenses"] is None for p in data["trend"]["points"]))
        self.assertTrue(all(p["net_profit"] is None for p in data["monthly"]))
        self.assertTrue(data["period"]["complete"])  # September 2026 has ended

    def test_expense_tables_not_migrated_yet(self):
        """Before accounting migration 0005 is applied the P&L still answers --
        expenses and net profit are unavailable, never an error or zero."""
        from unittest import mock
        with mock.patch("reports.profit_loss.expenses_available", return_value=False):
            data = self.statement()
            st = data["statement"]
            self.assertEqual(st["data_quality"]["expense_status"], "unavailable")
            self.assertFalse(st["data_quality"]["expenses_tracked"])
            self.assertIsNone(st["expense_count"])
            self.assertIsNone(st["net_profit"])
            self.assertEqual(st["gross_profit"], 2000)
            tx = self.get(self.client, TX, self.kb, kind="expenses", **SEPT).json()
            self.assertEqual((tx["expenses_available"], tx["count"]), (False, 0))
            stores = self.get(self.client, STORES, **SEPT).json()
            self.assertIsNone(stores["shared_expenses"])
            self.assertIsNone(stores["consolidated"]["net_profit"])

    def test_revenue_reconciles_with_invoice_net_totals(self):
        settled = Invoice.objects.filter(stock_point=self.kb, date__range=(date(2026, 9, 1), date(2026, 9, 30)), status__in=Invoice.SETTLED)
        self.assertEqual(self.statement()["statement"]["revenue"], sum(i.net_total for i in settled))

    def test_payments_are_not_counted_again(self):
        # settling posted cash-book entries for these invoices; revenue is unchanged by them
        from accounting.models import CashEntry
        CashEntry.objects.create(date=date(2026, 9, 5), particulars="Sale", type=CashEntry.IN, amount=130000,
                                 by=self.superuser, invoice=self.s1)
        self.assertEqual(self.statement()["statement"]["revenue"], 102000)

    def test_stores_do_not_mix(self):
        st = self.statement(store=self.np)["statement"]
        self.assertEqual((st["revenue"], st["cogs"], st["transactions"]), (40000, 30000, 1))

    def test_trend_and_monthly_comparison(self):
        data = self.statement()
        self.assertEqual(data["trend"]["granularity"], "day")
        self.assertEqual(len(data["trend"]["points"]), 30)
        self.assertEqual(sum(p["revenue"] for p in data["trend"]["points"]), 102000)
        self.assertEqual(sum(p["cogs"] for p in data["trend"]["points"]), 100000)
        months = [p["bucket"] for p in data["monthly"]]
        self.assertEqual(months, ["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"])
        aug = data["monthly"][4]
        self.assertEqual((aug["revenue"], aug["cogs"], aug["gross_profit"]), (40000, 30000, 10000))
        self.assertEqual(data["monthly"][5]["revenue"], 102000)

    def test_long_period_trend_is_monthly(self):
        data = self.statement(period="custom", date_from="2026-01-01", date_to="2026-12-31")
        self.assertEqual(data["trend"]["granularity"], "month")
        self.assertEqual(len(data["trend"]["points"]), 12)
        self.assertEqual(data["statement"]["revenue"], 102000 + 40000 + 40000)

    def test_transactions_behind_the_totals(self):
        rows = self.get(self.client, TX, self.kb, **SEPT).json()
        self.assertEqual(rows["count"], 5)
        self.assertEqual(sum(r["revenue"] for r in rows["results"]), 102000)
        s1 = next(r for r in rows["results"] if r["code"] == self.s1.code)
        self.assertEqual((s1["billed"], s1["refunded"], s1["revenue"], s1["cogs"], s1["gross_profit"]), (130000, 40000, 90000, 65000, 25000))
        refunds = self.get(self.client, TX, self.kb, kind="refunds", **SEPT).json()
        self.assertEqual(refunds["count"], 2)
        self.assertEqual(sorted(r["cogs_reversed"] for r in refunds["results"]), [0, 30000])
        self.assertEqual(self.get(self.client, TX, self.kb, kind="receivables", **SEPT).json()["count"], 1)
        cancelled = self.get(self.client, TX, self.kb, kind="cancelled", **SEPT).json()
        self.assertEqual((cancelled["count"], cancelled["results"][0]["revenue"]), (1, 0))
        repairs = self.get(self.client, TX, self.kb, source="repair", **SEPT).json()
        self.assertEqual((repairs["count"], {r["cogs"] for r in repairs["results"]}), (2, {None}))
        page = self.get(self.client, TX, self.kb, page_size=2, page=3, **SEPT).json()
        self.assertEqual((page["count"], len(page["results"])), (5, 1))

    def test_store_comparison_and_consolidated_total(self):
        data = self.get(self.client, STORES, **SEPT).json()
        self.assertTrue(data["can_compare"])
        by_store = {r["store"]["id"]: r for r in data["stores"]}
        self.assertEqual((by_store[self.kb.id]["revenue"], by_store[self.np.id]["revenue"]), (102000, 40000))
        self.assertEqual(data["consolidated"]["revenue"], 142000)
        self.assertEqual(data["consolidated"]["cogs"], 130000)

    def test_query_count_does_not_grow_with_invoices(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count():
            with CaptureQueriesContext(connection) as q:
                self.assertEqual(self.get(self.client, PL, self.kb, **SEPT).status_code, 200)
            return len(q)

        before = count()
        for day in range(1, 11):
            self.invoice(self.kb, date(2026, 9, day), [self.sale_line(self.a, 1), self.sale_line(self.b, 2)])
        self.assertEqual(count(), before)

    def test_missing_cost_marks_cogs_incomplete(self):
        free = Variant.objects.create(product=self.a.product, code="V-Z", spec="No cost", mrp=1000, sell_price=900, cost=0)
        self.invoice(self.np, date(2026, 9, 6), [self.sale_line(free, 1)])
        quality = self.statement(store=self.np)["statement"]["data_quality"]
        self.assertEqual((quality["cogs_complete"], quality["missing_cost_lines"], quality["missing_cost_value"]), (False, 1, 900))

    def test_fully_costed_store_is_complete(self):
        quality = self.statement(store=self.np)["statement"]["data_quality"]
        self.assertTrue(quality["cogs_complete"])
        self.assertEqual(quality["uncosted_revenue"], 0)

    def test_empty_period(self):
        data = self.statement(period="custom", date_from="2025-01-01", date_to="2025-01-07")
        st = data["statement"]
        self.assertEqual((st["revenue"], st["cogs"], st["gross_profit"], st["transactions"]), (0, 0, 0, 0))
        self.assertIsNone(st["gross_margin_pct"])
        self.assertEqual(len(data["trend"]["points"]), 7)
        self.assertTrue(all(p["revenue"] == 0 for p in data["trend"]["points"]))

    def test_meta_and_no_caching(self):
        response = self.get(self.client, PL, self.kb, **SEPT)
        data = response.json()
        self.assertEqual(data["store"]["name"], "Karol Bagh")
        self.assertEqual(data["period"], {"key": "custom", "start": "2026-09-01", "end": "2026-09-30", "days": 30, "complete": True})
        self.assertIn("generated_at", data)
        self.assertIn("no-store", response["Cache-Control"])


class PeriodTests(TestCase):
    TODAY = date(2026, 10, 30)  # a Friday

    def period(self, key, today=TODAY, **params):
        p = resolve_period({"period": key, **params}, today=today)
        return p.start, p.end

    def test_presets(self):
        t = self.TODAY
        self.assertEqual(self.period("today"), (t, t))
        self.assertEqual(self.period("yesterday"), (date(2026, 10, 29),) * 2)
        self.assertEqual(self.period("this_week"), (date(2026, 10, 26), t))
        self.assertEqual(self.period("this_month"), (date(2026, 10, 1), t))
        self.assertEqual(self.period("last_month"), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(self.period("this_year"), (date(2026, 1, 1), t))
        self.assertEqual(resolve_period({}, today=t).key, "this_month")

    def test_year_and_month_boundaries(self):
        self.assertEqual(self.period("last_month", today=date(2026, 1, 15)), (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(self.period("yesterday", today=date(2026, 1, 1)), (date(2025, 12, 31),) * 2)
        self.assertEqual(self.period("last_month", today=date(2024, 3, 1)), (date(2024, 2, 1), date(2024, 2, 29)))

    def test_custom_range_is_inclusive_and_validated(self):
        self.assertEqual(self.period("custom", date_from="2026-09-01", date_to="2026-09-01"), (date(2026, 9, 1),) * 2)
        for params in ({"date_from": "2026-09-02", "date_to": "2026-09-01"}, {"date_from": "nope", "date_to": "2026-09-01"},
                       {"date_from": "2026-09-01"}, {"date_from": "2010-01-01", "date_to": "2026-01-01"}):
            with self.assertRaises(ValidationError):
                self.period("custom", **params)
        with self.assertRaises(ValidationError):
            self.period("forever")

    def test_bad_period_is_a_400(self):
        kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        client = client_for(make_user("root", superuser=True))
        self.assertEqual(client.get(PL, {"store": kb.id, "period": "custom", "date_from": "2026-09-30", "date_to": "2026-09-01"}).status_code, 400)
        self.assertEqual(client.get(PL, {"store": kb.id, "period": "forever"}).status_code, 400)


class ProfitLossAccessTests(ProfitLossTestBase):
    def setUp(self):
        super().setUp()
        self.invoice(self.kb, date(2026, 9, 5), [self.sale_line(self.a, 1)])
        self.invoice(self.np, date(2026, 9, 5), [self.sale_line(self.b, 1)])

    def assertDenied(self, user):
        client = client_for(user)
        for store in (self.kb, self.np):
            for url in (PL, TX):
                response = self.get(client, url, store, **SEPT)
                self.assertEqual(response.status_code, 403, f"{user} {url}")
                self.assertNotIn("revenue", response.content.decode())
        response = self.get(client, STORES, **SEPT)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("revenue", response.content.decode())

    def test_superuser_sees_every_store(self):
        client = client_for(self.superuser)
        for store in (self.kb, self.np):
            self.assertEqual(self.get(client, PL, store, **SEPT).status_code, 200)
        self.assertEqual(client.get("/api/users/me/").json()["can_view_profit_loss"], True)

    def test_owner_role_with_the_permission_can_compare(self):
        owner = client_for(make_user("owner", ["reports.profit_loss"], owner=True))
        self.assertEqual(self.get(owner, PL, self.np, **SEPT).status_code, 200)
        data = self.get(owner, STORES, **SEPT).json()
        self.assertEqual((data["can_compare"], len(data["stores"]), data["consolidated"]["revenue"]), (True, 2, 90000))

    def test_admin_sees_only_their_own_store(self):
        admin = make_user("kb-admin", ADMIN, stock_point=self.kb)
        client = client_for(admin)
        self.assertEqual(self.get(client, PL, self.kb, **SEPT).json()["statement"]["revenue"], 40000)
        # another store's id -- in the query string, as a list, or on the transactions endpoint -- is refused
        for url in (PL, TX):
            self.assertEqual(self.get(client, url, self.np, **SEPT).status_code, 403)
        self.assertEqual(client.get(PL, {"store": [self.np.id, self.kb.id], **SEPT}).status_code, 400)
        stores = self.get(client, STORES, **SEPT).json()
        self.assertEqual([r["store"]["id"] for r in stores["stores"]], [self.kb.id])
        self.assertEqual((stores["can_compare"], stores["consolidated"]), (False, None))
        self.assertNotIn("Nehru", str(stores))

    def test_admin_without_the_permission_is_refused(self):
        self.assertDenied(make_user("kb-admin", ["roles.manage", "reports.export"], stock_point=self.kb))

    def test_permission_without_admin_tier_is_refused(self):
        # e.g. an Accounts role someone gave the permission to -- not an Admin
        self.assertDenied(make_user("accounts", ["reports.export", "cashbook.view", "reports.profit_loss"], stock_point=self.kb))

    def test_ordinary_staff_get_nothing(self):
        staff = make_user("sales", ["invoices.view", "invoices.create"], stock_point=self.kb)
        staff.is_staff = True  # is_staff is not "Admin"
        staff.save()
        self.assertDenied(staff)
        me = client_for(staff).get("/api/users/me/").json()
        self.assertFalse(me["can_view_profit_loss"])
        self.assertTrue(PermissionDeniedLog.objects.filter(user=staff, required_perm="reports.profit_loss").exists())

    def test_unassigned_admin_is_refused(self):
        admin = make_user("floating", ADMIN)
        client = client_for(admin)
        self.assertEqual(self.get(client, PL, self.kb, **SEPT).status_code, 403)
        self.assertEqual(self.get(client, STORES, **SEPT).status_code, 403)

    def test_anonymous_is_refused(self):
        self.assertIn(self.get(APIClient(), PL, self.kb, **SEPT).status_code, (401, 403))

    def test_store_parameter_is_validated(self):
        client = client_for(self.superuser)
        self.assertEqual(client.get(PL, SEPT).status_code, 400)
        self.assertEqual(client.get(PL, {"store": "abc", **SEPT}).status_code, 400)
        self.assertEqual(client.get(PL, {"store": 99999, **SEPT}).status_code, 404)

    def test_migration_grants_owner_and_admin_roles_only(self):
        import importlib

        from django.apps import apps

        from accounts.models import Permission, Role
        migration = importlib.import_module("accounts.migrations.0010_profit_loss_permission")
        roles = {slug: Role.objects.get_or_create(slug=slug, defaults={"label": slug})[0] for slug in ("owner", "manager", "accountant")}
        migration.add_permission(apps, None)
        perm = Permission.objects.get(codename="reports.profit_loss")
        self.assertEqual(set(perm.roles.values_list("slug", flat=True)), {"owner", "manager"})
        self.assertFalse(roles["accountant"].permissions.filter(pk=perm.pk).exists())
