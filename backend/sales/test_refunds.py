"""Refunds and returns on paid invoices, and their effect on the books and revenue."""
import os
from datetime import date
from unittest import mock

from django.test import TestCase

from accounting.models import BankEntry, CashEntry
from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice
from sales.services import create_invoice


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class RefundTests(TestCase):
    def setUp(self):
        self.seller = client_for(make_user("seller", ["invoices.view", "invoices.create", "invoices.settle"]))
        self.accounts_user = make_user("accounts", ["invoices.view", "invoices.refund", "reports.export"])
        self.accounts = client_for(self.accounts_user)
        self.shop = StockPoint.objects.create(slug="shop", name="Main Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543211", joined=date.today())
        product = Product.objects.create(model_name="Laptop", product_code="P-1")
        self.a = Variant.objects.create(product=product, code="V-A", spec="8GB", mrp=1, sell_price=40000, cost=1)
        self.b = Variant.objects.create(product=product, code="V-B", spec="16GB", mrp=1, sell_price=50000, cost=1)
        self.stock_a = Stock.objects.create(variant=self.a, stock_point=self.shop, quantity=3)
        Stock.objects.create(variant=self.b, stock_point=self.shop, quantity=3)

    def paid_sale(self, method="UPI"):
        inv = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.a.id, "qty": 2, "price": 40000}, {"variant": self.b.id, "qty": 1, "price": 50000}],
        }, format="json").json()
        self.seller.post(f"/api/invoices/{inv['id']}/settle/", {"pay_method": method, "payment_reference": "UTR1"}, format="json")
        return inv

    def refund(self, inv_id, **body):
        return self.accounts.post(f"/api/invoices/{inv_id}/refund/", {"method": "Bank transfer", "reference": "NEFT9", "reason": "Returned", **body}, format="json")

    def test_returning_one_item_restocks_it_and_pays_out_of_the_bank_book(self):
        inv = self.paid_sale()
        line_a = next(i for i in inv["items"] if i["variant"] == self.a.id)
        response = self.refund(inv["id"], items=[{"item": line_a["id"], "qty": 1}])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["status"], data["refunded_total"], data["net_total"]), ("Paid", 40000, 90000))
        self.assertEqual(next(i for i in data["items"] if i["id"] == line_a["id"])["returned_qty"], 1)
        self.stock_a.refresh_from_db()
        self.assertEqual(self.stock_a.quantity, 3 - 2 + 1)
        out = BankEntry.objects.get(refund__invoice_id=inv["id"])
        self.assertEqual((out.type, out.amount, out.reference), (BankEntry.OUT, 40000, "NEFT9"))
        # revenue is net of the refund
        report = self.accounts.get("/api/reports/sales-summary/").json()
        self.assertEqual(report["total_revenue_paid"], 130000 - 40000)

    def test_full_refund_marks_invoice_refunded_and_can_skip_restock(self):
        inv = self.paid_sale(method="Cash")
        items = [{"item": i["id"], "qty": i["qty"]} for i in inv["items"]]
        response = self.refund(inv["id"], items=items, restock=False, method="Cash", reference="")
        self.assertEqual(response.json()["status"], "Refunded")
        self.stock_a.refresh_from_db()
        self.assertEqual(self.stock_a.quantity, 1)  # damaged -- not put back
        self.assertEqual(CashEntry.objects.get(refund__invoice_id=inv["id"]).type, CashEntry.OUT)
        again = self.refund(inv["id"], items=items[:1])
        self.assertEqual(again.status_code, 400)
        self.assertIn("already been refunded", again.json()["detail"])

    def test_cannot_return_more_than_was_sold(self):
        inv = self.paid_sale()
        line_a = next(i for i in inv["items"] if i["variant"] == self.a.id)
        self.assertEqual(self.refund(inv["id"], items=[{"item": line_a["id"], "qty": 1}]).status_code, 200)
        response = self.refund(inv["id"], items=[{"item": line_a["id"], "qty": 2}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("only 1 left to return", response.json()["detail"])

    def test_refund_needs_a_paid_invoice_reason_and_reference(self):
        unpaid = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.a.id, "qty": 1, "price": 40000}],
        }, format="json").json()
        self.assertIn("Only a paid invoice", self.refund(unpaid["id"], items=[{"item": unpaid["items"][0]["id"], "qty": 1}]).json()["detail"])
        inv = self.paid_sale()
        item = [{"item": inv["items"][0]["id"], "qty": 1}]
        self.assertIn("reason", self.refund(inv["id"], items=item, reason=" ").json()["detail"])
        self.assertIn("reference", self.refund(inv["id"], items=item, reference="").json()["detail"])

    def test_amount_refund_on_a_service_invoice(self):
        inv = create_invoice(
            source=Invoice.REPAIR, party=self.party, stock_point=self.shop, date=date.today(),
            status=Invoice.PAID, pay_method="UPI", paid_on=date.today(),
            lines=[{"description": "Screen replacement", "qty": 1, "price": 6000}],
        )
        self.assertIn("Only ₹6000 is left", self.refund(inv.id, amount=7000).json()["detail"])
        response = self.refund(inv.id, amount=1000)
        self.assertEqual((response.json()["status"], response.json()["net_total"]), ("Paid", 5000))

    def test_refund_permission(self):
        inv = self.paid_sale()
        response = self.seller.post(f"/api/invoices/{inv['id']}/refund/", {"amount": 1}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_refunded_invoice_cannot_be_cancelled_or_settled_again(self):
        inv = self.paid_sale()
        self.refund(inv["id"], items=[{"item": i["id"], "qty": i["qty"]} for i in inv["items"]])
        self.assertEqual(self.seller.post(f"/api/invoices/{inv['id']}/cancel/", {"reason": "x"}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(f"/api/invoices/{inv['id']}/settle/", {"pay_method": "Cash"}, format="json").status_code, 400)
