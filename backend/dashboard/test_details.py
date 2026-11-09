"""Dashboard -> click a metric: the records behind it add up to the card."""
from datetime import date, timedelta

from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from repairs.models import RepairTicket
from sales.models import Invoice
from sales.services import create_invoice


class MetricDetailTests(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543211", joined=date(2026, 1, 1))
        product = Product.objects.create(model_name="Laptop", product_code="P-D")
        self.v = Variant.objects.create(product=product, code="V-D", spec="8GB", mrp=45000, sell_price=40000, cost=30000)
        Stock.objects.create(variant=self.v, stock_point=self.kb, quantity=3)
        Stock.objects.create(variant=self.v, stock_point=self.np, quantity=5)
        self.owner = client_for(make_user("dash-owner", superuser=True))

    def sale(self, store, status=Invoice.PAID, source=Invoice.SALE):
        return create_invoice(lines=[{"variant": self.v, "qty": 1, "price": 40000}], party=self.party, stock_point=store,
                              date=date.today(), status=status, source=source, pay_method="Cash" if status == Invoice.PAID else "")

    def detail(self, client, metric, **params):
        response = client.get(f"/api/dashboard/detail/{metric}/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_rows_add_up_to_the_card(self):
        self.sale(self.kb)
        self.sale(self.np)
        self.sale(self.kb, status=Invoice.LINK_SENT)
        summary = self.owner.get("/api/dashboard/summary/").json()
        revenue = self.detail(self.owner, "revenue_paid")
        self.assertEqual(revenue["total"]["value"], summary["revenue_paid"])
        self.assertEqual(revenue["count"], 2)
        pending = self.detail(self.owner, "pending")
        self.assertEqual(pending["total"]["value"], summary["pending_collections"])
        stock = self.detail(self.owner, "stock")
        self.assertEqual(stock["total"]["value"], summary["stock_value"])

    def test_channel_filter_and_low_stock(self):
        self.sale(self.kb)
        self.sale(self.np)
        self.assertEqual(self.detail(self.owner, "revenue_paid", channel="kb")["count"], 1)
        low = self.detail(self.owner, "low_stock", channel="kb")
        self.assertEqual(low["rows"][0]["units"], 3)

    def test_overdue_repairs_list_the_late_jobs(self):
        RepairTicket.objects.create(code="RT-LATE", party=self.party, brand="Dell", model_name="X", stock_point=self.kb,
                                    issue="No power", received=date.today() - timedelta(days=9), expected=date.today() - timedelta(days=2))
        rows = self.detail(self.owner, "repair_overdue")["rows"]
        self.assertEqual((rows[0]["code"], rows[0]["late_days"]), ("RT-LATE", 2))

    def test_store_staff_see_only_their_store_and_their_sections(self):
        self.sale(self.kb)
        self.sale(self.np)
        staff = client_for(make_user("dash-staff", ["dashboard.view", "invoices.view"], stock_point=self.kb))
        self.assertEqual(self.detail(staff, "revenue_paid", channel="np")["count"], 1)  # pinned to Karol Bagh
        self.assertEqual(staff.get("/api/dashboard/detail/rental_risk/").status_code, 403)
        self.assertEqual(staff.get("/api/dashboard/detail/nonsense/").status_code, 404)
