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


class MetricDetailPagingTests(MetricDetailTests):
    """Big lists come a page at a time; count and total still cover everything."""

    def test_paid_sales_are_paged_and_totalled_in_the_database(self):
        for _ in range(7):
            self.sale(self.kb)
        first = self.detail(self.owner, "revenue_paid", page_size=3)
        self.assertEqual((first["count"], first["pages"], first["page_number"], len(first["rows"])), (7, 3, 1, 3))
        self.assertEqual(first["total"]["value"], 7 * 40000)
        last = self.detail(self.owner, "revenue_paid", page_size=3, page=3)
        self.assertEqual(len(last["rows"]), 1)
        codes = {r["code"] for p in (1, 2, 3) for r in self.detail(self.owner, "revenue_paid", page_size=3, page=p)["rows"]}
        self.assertEqual(len(codes), 7)
        # out of range / nonsense values fall back safely
        self.assertEqual(self.detail(self.owner, "revenue_paid", page_size=3, page=99)["page_number"], 3)
        self.assertEqual(self.detail(self.owner, "revenue_paid", page_size="x")["page_size"], 50)
        self.assertEqual(self.detail(self.owner, "revenue_paid", page_size=10000)["page_size"], 200)

    def test_pending_lists_each_customer_once_with_a_reminder(self):
        from parties.models import Party
        other = Party.objects.create(name="Second Buyer", type=Party.RETAIL, phone="9811122233", joined=date(2026, 1, 1))
        self.sale(self.kb, status=Invoice.LINK_SENT)
        self.sale(self.np, status=Invoice.LINK_SENT)
        create_invoice(lines=[{"variant": self.v, "qty": 1, "price": 5000}], party=other, stock_point=self.kb,
                       date=date.today(), status=Invoice.LINK_SENT, source=Invoice.SALE)
        summary = self.owner.get("/api/dashboard/summary/").json()
        data = self.detail(self.owner, "pending")
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["total"]["value"], summary["pending_collections"])
        top = data["rows"][0]
        self.assertEqual((top["customer"], top["phone"], top["invoice_count"], top["amount"]), ("Buyer", "9876543211", 2, 80000))
        reminder = top["copy"][0]["text"]
        self.assertIn("Buyer", reminder)
        self.assertIn("80,000", reminder)
        self.assertEqual(top["copy"][1]["text"], "9876543211")
        self.assertEqual(self.detail(self.owner, "pending", page_size=1, page=2)["rows"][0]["customer"], "Second Buyer")
