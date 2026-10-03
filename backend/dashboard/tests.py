from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Permission, Role
from catalog.models import Product, Stock, StockPoint, Variant
from dashboard.layouts import effective_layout
from dashboard.models import DashboardLayout, DashboardLayoutItem, DashboardWidget
from parties.models import Party
from sales.models import Invoice, InvoiceItem


class DashboardLayoutTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="dash-owner", password="safe-test-password", is_superuser=True)
        self.repair_role = Role.objects.create(slug="test_repair_only", label="Test repair only")
        self.repair_role.permissions.add(Permission.objects.get_or_create(codename="repairs.view", defaults={"description": "View repairs"})[0])
        self.tech = User.objects.create_user(username="dash-tech", password="safe-test-password", role=self.repair_role)

    def keys(self, user):
        return [w["key"] for w in effective_layout(user)["widgets"]]

    def test_catalog_is_seeded_with_current_dashboard_elements(self):
        self.assertEqual(DashboardWidget.objects.count(), 14)
        self.assertTrue(DashboardWidget.objects.filter(key="chart-monthly-revenue", kind="chart", chart_type="line").exists())

    def test_superuser_gets_every_widget_in_default_order(self):
        layout = effective_layout(self.owner)
        self.assertEqual(layout["source"], "default")
        self.assertEqual(self.keys(self.owner), list(DashboardWidget.objects.values_list("key", flat=True)))

    def test_role_only_sees_widgets_for_its_sections(self):
        sections = {w["section"] for w in effective_layout(self.tech)["widgets"]}
        # repairs.view also unlocks the stock section (parts on the shelf)
        self.assertEqual(sections, {"repairs", "stock"})

    def test_user_layout_beats_role_layout_and_keeps_unplaced_widgets(self):
        stages = DashboardWidget.objects.get(key="panel-repair-stages")
        overdue = DashboardWidget.objects.get(key="kpi-repairs-overdue")
        role_layout = DashboardLayout.objects.create(role=self.repair_role)
        DashboardLayoutItem.objects.create(layout=role_layout, widget=overdue, position=0)
        self.assertEqual(effective_layout(self.tech)["source"], "role")
        self.assertEqual(self.keys(self.tech)[0], "kpi-repairs-overdue")

        mine = DashboardLayout.objects.create(user=self.tech)
        DashboardLayoutItem.objects.create(layout=mine, widget=stages, position=0, width=6, settings={"compact": True})
        DashboardLayoutItem.objects.create(layout=mine, widget=overdue, position=1, is_visible=False)
        layout = effective_layout(self.tech)
        self.assertEqual(layout["source"], "user")
        first, second = layout["widgets"][:2]
        self.assertEqual((first["key"], first["width"], first["settings"]), ("panel-repair-stages", 6, {"compact": True}))
        self.assertFalse(second["visible"])
        # widgets the user never placed still show up, after the saved ones
        self.assertEqual(len(layout["widgets"]), len(self.keys(self.tech)))
        self.assertIn("kpi-stock-on-hand", self.keys(self.tech)[2:])

    def test_saved_layout_cannot_leak_widgets_from_hidden_sections(self):
        mine = DashboardLayout.objects.create(user=self.tech)
        DashboardLayoutItem.objects.create(layout=mine, widget=DashboardWidget.objects.get(key="kpi-sales-revenue"))
        self.assertNotIn("kpi-sales-revenue", self.keys(self.tech))

    def test_layout_must_have_exactly_one_owner(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DashboardLayout.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DashboardLayout.objects.create(role=self.repair_role, user=self.tech)

    def test_layout_endpoint(self):
        client = APIClient()
        client.force_authenticate(self.tech)
        response = client.get("/api/dashboard/layout/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grid_columns"], 12)
        summary = client.get("/api/dashboard/summary/").json()
        self.assertEqual(summary["sections"], {"stock": True, "sales": False, "repairs": True, "rentals": False})


class DashboardSummaryFromDatabaseTests(TestCase):
    """
    The dashboard figures are computed from database rows, not
    hard-coded: start from an empty database, add records, and watch
    /api/dashboard/summary/ follow them.
    """

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="summary-owner", password="safe-test-password", is_superuser=True
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.web = StockPoint.objects.create(slug="test-web", name="Test Website", kind=StockPoint.ONLINE)
        self.party = Party.objects.create(name="Test Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        product = Product.objects.create(brand="Dell", model_name="Latitude 5420", product_code="TEST-LAP-0001")
        self.variant = Variant.objects.create(
            product=product, code="TEST-SKU-0001", spec="i5 / 16GB / 512GB", mrp=50000, sell_price=45000, cost=40000
        )

    def summary(self, **params):
        response = self.client.get("/api/dashboard/summary/", params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def make_invoice(self, code, status, qty, price, stock_point=None, on=None):
        invoice = Invoice.objects.create(
            code=code, party=self.party, stock_point=stock_point or self.shop,
            date=on or date.today(), status=status,
        )
        InvoiceItem.objects.create(invoice=invoice, variant=self.variant, qty=qty, price=price)
        return invoice

    def test_empty_database_shows_zeros(self):
        data = self.summary()
        self.assertEqual(data["revenue_paid"], 0)
        self.assertEqual(data["pending_collections"], 0)
        self.assertEqual(data["open_invoice_count"], 0)
        self.assertEqual(data["total_stock_units"], 0)
        self.assertEqual(data["rental_count"], 0)

    def test_revenue_and_pending_follow_invoices(self):
        self.make_invoice("INV-T1", Invoice.PAID, qty=2, price=45000)
        self.make_invoice("INV-T2", Invoice.LINK_SENT, qty=1, price=30000)
        data = self.summary()
        self.assertEqual(data["revenue_paid"], 90000)
        self.assertEqual(data["pending_collections"], 30000)
        self.assertEqual(data["open_invoice_count"], 1)

        # Settle the open invoice in the database -> the dashboard moves with it.
        Invoice.objects.filter(code="INV-T2").update(status=Invoice.PAID)
        data = self.summary()
        self.assertEqual(data["revenue_paid"], 120000)
        self.assertEqual(data["pending_collections"], 0)

    def test_stock_figures_and_low_stock_follow_stock_rows(self):
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=3)
        Stock.objects.create(variant=self.variant, stock_point=self.web, quantity=7)
        data = self.summary()
        self.assertEqual(data["total_stock_units"], 10)
        self.assertEqual(data["stock_value"], 10 * 40000)
        self.assertEqual(data["low_stock_count"], 0)

        # Drop total stock to 4 or fewer -> it shows up as a low-stock alert.
        Stock.objects.filter(stock_point=self.web).update(quantity=1)
        data = self.summary()
        self.assertEqual(data["total_stock_units"], 4)
        self.assertEqual([row["variant_code"] for row in data["low_stock"]], ["TEST-SKU-0001"])

    def test_filters_narrow_the_figures(self):
        self.make_invoice("INV-SHOP", Invoice.PAID, qty=1, price=45000, stock_point=self.shop, on=date(2026, 1, 15))
        self.make_invoice("INV-WEB", Invoice.PAID, qty=1, price=20000, stock_point=self.web, on=date(2026, 3, 10))

        self.assertEqual(self.summary()["revenue_paid"], 65000)
        self.assertEqual(self.summary(channel="test-web")["revenue_paid"], 20000)
        self.assertEqual(self.summary(date_from="2026-02-01")["revenue_paid"], 20000)
        self.assertEqual(self.summary(date_to="2026-01-31")["revenue_paid"], 45000)

        by_channel = {c["id"]: c for c in self.summary()["channel_sales"]}
        self.assertEqual(by_channel["test-shop"]["revenue_paid"], 45000)
        self.assertEqual(by_channel["test-web"]["units_sold"], 1)
