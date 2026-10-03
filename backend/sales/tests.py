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

    def test_settle_records_how_and_when_it_was_paid(self):
        invoice_id = self.create_invoice().json()["id"]
        response = self.seller.post(f"/api/invoices/{invoice_id}/settle/", {
            "pay_method": "UPI", "payment_reference": "UTR 412345678901", "paid_on": "2026-01-05",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["settled_by_name"], "seller")
        invoice = Invoice.objects.get(id=invoice_id)
        self.assertEqual(
            (invoice.status, invoice.pay_method, invoice.payment_reference, invoice.paid_on.isoformat()),
            (Invoice.PAID, "UPI", "UTR 412345678901", "2026-01-05"),
        )
        # can't be settled twice
        again = self.seller.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_settle_validation(self):
        invoice_id = self.create_invoice().json()["id"]
        url = f"/api/invoices/{invoice_id}/settle/"
        self.assertEqual(self.seller.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(url, {"pay_method": "Bitcoin"}, format="json").status_code, 400)
        # non-cash payments need a reference to trace them
        self.assertEqual(self.seller.post(url, {"pay_method": "UPI"}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(url, {"pay_method": "Cash", "paid_on": "2999-01-01"}, format="json").status_code, 400)
        # cash needs no reference; paid_on defaults to today
        cash = self.seller.post(url, {"pay_method": "Cash"}, format="json")
        self.assertEqual(cash.status_code, 200)
        self.assertEqual(cash.json()["paid_on"], date.today().isoformat())

    def test_payment_fields_cannot_be_set_on_create(self):
        response = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "payment_reference": "fake", "items": [{"variant": self.variant.id, "qty": 1, "price": 1}],
        }, format="json")
        self.assertEqual(response.json()["payment_reference"], "")

    def test_print_data(self):
        self.shop.address = "12 Main Road, Karol Bagh, New Delhi"
        self.shop.gstin = "07ABCDE1234F1Z5"
        self.shop.save()
        self.variant.product.hsn = "84713010"
        self.variant.product.save()
        invoice_id = self.create_invoice(qty=2).json()["id"]

        data = self.seller.get(f"/api/invoices/{invoice_id}/print-data/").json()
        self.assertEqual(data["seller"]["branch"], "Test Shop")
        self.assertEqual(data["seller"]["address"], "12 Main Road, Karol Bagh, New Delhi")
        self.assertEqual(data["seller"]["gstin"], "07ABCDE1234F1Z5")
        self.assertEqual(data["buyer"]["name"], "Test Customer")
        self.assertEqual(
            {k: data["items"][0][k] for k in ("n", "hsn", "qty", "rate", "amount")},
            {"n": 1, "hsn": "84713010", "qty": 2, "rate": 35000, "amount": 70000},
        )
        self.assertEqual((data["total_qty"], data["total"]), (2, 70000))
        self.assertEqual(client_for(make_user("no-invoices")).get(f"/api/invoices/{invoice_id}/print-data/").status_code, 403)

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
        self.assertEqual(viewer.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json").status_code, 403)

        nobody = client_for(make_user("nobody"))
        self.assertEqual(nobody.get("/api/invoices/").status_code, 403)
