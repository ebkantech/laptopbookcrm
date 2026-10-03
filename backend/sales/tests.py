from datetime import date

from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from sales.models import Invoice, InvoiceItem


class InvoiceApiTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Test Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        product = Product.objects.create(brand="HP", model_name="EliteBook 840", product_code="TEST-LAP-0001")
        self.variant = Variant.objects.create(
            product=product, code="TEST-SKU-0001", spec="i5 / 8GB", mrp=40000, sell_price=35000, cost=30000
        )
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=10)
        self.seller = client_for(make_user("seller", ["invoices.view", "invoices.create", "invoices.settle"]))

    def create_invoice(self, client=None, qty=2, price=35000):
        return (client or self.seller).post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.variant.id, "qty": qty, "price": price}],
        }, format="json")

    def test_create_invoice_generates_code_computes_total_and_decrements_stock(self):
        response = self.create_invoice(qty=3)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["code"].startswith("INV-"))
        self.assertEqual(body["total"], 3 * 35000)
        self.assertEqual(body["status"], Invoice.LINK_SENT)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)

    def test_invoice_needs_at_least_one_item(self):
        response = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(), "items": [],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.json())

    def test_settle_marks_invoice_paid(self):
        invoice_id = self.create_invoice().json()["id"]
        response = self.seller.post(f"/api/invoices/{invoice_id}/settle/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.get(id=invoice_id).status, Invoice.PAID)

    def test_list_filters_by_status_and_party(self):
        paid = Invoice.objects.create(code="INV-P", party=self.party, stock_point=self.shop, date=date.today(), status=Invoice.PAID)
        InvoiceItem.objects.create(invoice=paid, variant=self.variant, qty=1, price=1)
        other = Party.objects.create(name="Other", type=Party.RETAIL, phone="9876500000", joined=date.today())
        Invoice.objects.create(code="INV-O", party=other, stock_point=self.shop, date=date.today(), status=Invoice.OVERDUE)

        codes = lambda r: sorted(i["code"] for i in results(r))
        self.assertEqual(codes(self.seller.get("/api/invoices/", {"status": Invoice.PAID})), ["INV-P"])
        self.assertEqual(codes(self.seller.get("/api/invoices/", {"party": other.id})), ["INV-O"])

    def test_permissions(self):
        viewer = client_for(make_user("viewer", ["invoices.view"]))
        self.assertEqual(viewer.get("/api/invoices/").status_code, 200)
        self.assertEqual(self.create_invoice(client=viewer).status_code, 403)

        invoice_id = self.create_invoice().json()["id"]
        self.assertEqual(viewer.post(f"/api/invoices/{invoice_id}/settle/").status_code, 403)

        nobody = client_for(make_user("nobody"))
        self.assertEqual(nobody.get("/api/invoices/").status_code, 403)
